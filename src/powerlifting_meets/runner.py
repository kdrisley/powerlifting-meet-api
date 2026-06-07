from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from powerlifting_meets import llm_geo
from powerlifting_meets.models import FederationMeta, Meet, MeetsResponse
from powerlifting_meets.normalize import normalize_country, normalize_state, resolve_location
from powerlifting_meets.scrapers.apf import APFScraper
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.powerlifting_america import PowerliftingAmericaScraper
from powerlifting_meets.scrapers.rps import RPSScraper
from powerlifting_meets.scrapers.spf import SPFScraper
from powerlifting_meets.scrapers.usapl import USAPLScraper
from powerlifting_meets.scrapers.uspa import USPAScraper

logger = logging.getLogger(__name__)

# URL of the previously published meets.json on GitHub Pages
PREVIOUS_DATA_URL = "https://kdrisley.github.io/powerlifting-meet-api/events"

# Published geo-inference cache. output/ isn't committed to the repo, but it is
# published to GitHub Pages, so the cache persists across runs the same way the
# meet-data fallback does (see fetch_previous_data).
GEO_CACHE_URL = "https://kdrisley.github.io/powerlifting-meet-api/geo_cache.json"

OUTPUT_DIR = Path("output")

ALL_SCRAPERS: list[type[BaseScraper]] = [
    USPAScraper,
    PowerliftingAmericaScraper,
    USAPLScraper,
    RPSScraper,
    SPFScraper,
    APFScraper,
]


def fetch_previous_data(url: str | None) -> MeetsResponse | None:
    """Fetch yesterday's events JSON from GitHub Pages for fallback."""
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        # The live JSON uses powermeet-compatible field names, so map back
        meets = []
        for e in data.get("events", []):
            # `link` is url-or-registration; recover the bare info url so the
            # round-trip doesn't promote a registration link into url.
            link = e.get("link") or None
            registration_url = e.get("registration_url") or None
            url = link if link != registration_url else None
            meets.append(Meet(
                name=e.get("evt_name", ""),
                federation=e.get("fed", ""),
                date_start=e.get("parsed_date", ""),
                state=e.get("state") or None,
                city=e.get("city") or None,
                country=e.get("country") or None,
                geo_inferred=bool(e.get("geo_inferred")),
                url=url,
                registration_url=registration_url,
                venue=e.get("venue") or None,
                status=e.get("status") or None,
                equipment=e.get("equipment") or None,
                restrictions=e.get("restrictions") or None,
                director_name=e.get("director_name") or None,
                director_email=e.get("director_email") or None,
                sanction=e.get("sanction") or None,
                event_type=e.get("event_type") or None,
            ))
        meta = {}
        for k, v in data.get("meta", {}).items():
            meta[k] = FederationMeta.model_validate(v)
        return MeetsResponse(
            generated_at=datetime.fromisoformat(data["generated_at"]),
            total_meets=data.get("total_meets", len(meets)),
            meets=meets,
            meta=meta,
        )
    except Exception as exc:
        logger.warning("Could not fetch previous data from %s: %s", url, exc)
        return None


def get_previous_meets_for_federation(
    previous: MeetsResponse | None,
    federation: str,
    today: date,
) -> list[Meet]:
    """Extract still-valid meets for a federation from previous data."""
    if previous is None:
        return []
    return [
        m for m in previous.meets
        if m.federation == federation and m.date_start >= today
    ]


def fetch_geo_cache(url: str | None) -> dict:
    """Load the previously published geo-inference cache from GitHub Pages.

    Returns an empty cache on any failure (first run, network hiccup) so the
    pipeline degrades to "infer everything fresh" rather than breaking.
    """
    if not url:
        return {}
    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Could not fetch geo cache from %s: %s", url, exc)
        return {}


def save_geo_cache(cache: dict, path: Path) -> None:
    """Write the geo cache so it's published alongside the events output."""
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def infer_missing_locations(meets: list[Meet], cache: dict) -> int:
    """LLM fallback for meets with neither a state nor a country.

    Runs after deterministic backfill, on the small residue parsing can't
    resolve. Each meet is keyed by identity plus a hash of its input signals,
    so a meet is sent to the model at most once across runs — a cache hit (even
    a low-confidence "couldn't tell") costs nothing. Mutates `meets` and
    `cache` in place; returns the number of meets a guess was applied to.
    """
    applied = 0
    calls = 0
    for m in meets:
        if m.state or m.country:
            continue
        key = llm_geo.cache_key(m)
        h = llm_geo.signals_hash(m)
        entry = cache.get(key)
        fresh = (
            entry
            and entry.get("signals_hash") == h
            and entry.get("schema_version") == llm_geo.SCHEMA_VERSION
        )
        if not fresh:
            guess = llm_geo.infer_location(m)
            if guess is None:
                # No API key or the call failed — retry next run, don't cache.
                continue
            calls += 1
            entry = {
                "schema_version": llm_geo.SCHEMA_VERSION,
                "signals_hash": h,
                "city": guess.city,
                "state": normalize_state(guess.state),
                "country": normalize_country(guess.country) or guess.country,
                "confidence": guess.confidence,
                "reasoning": guess.reasoning,
            }
            cache[key] = entry

        if entry.get("confidence", 0) < llm_geo.CONFIDENCE_THRESHOLD:
            continue
        changed = False
        if entry.get("state") and not m.state:
            m.state = entry["state"]
            changed = True
        if entry.get("country") and not m.country:
            m.country = entry["country"]
            changed = True
        if entry.get("city") and not m.city:
            m.city = entry["city"]
            changed = True
        if changed:
            m.geo_inferred = True
            applied += 1

    if calls:
        logger.info(
            "Gemini geo inference: %d new API call(s), %d meet(s) resolved", calls, applied
        )
    return applied


def backfill_locations(meets: list[Meet]) -> int:
    """Deterministically fill in missing state/country across all federations.

    Some scrapers leave a state-bearing location stranded in the `city` field
    (e.g. "Royal Oak MI") or a non-US meet with no state ("Port Elizabeth South
    Africa"). For any meet still missing a state, re-run the shared location
    parser over its `city` and `name` and adopt the first recognizable result.
    US meets that already have a state are stamped with country "United States"
    for a consistent, filterable feed. Mutates in place; returns the number of
    meets whose location fields changed.
    """
    changed = 0
    for m in meets:
        if m.state and not m.country:
            m.country = "United States"
            changed += 1
            continue
        if m.state:
            continue
        for source in (m.city, m.name):
            city, state, country = resolve_location(source)
            if not state and not country:
                continue
            if city:
                m.city = city
            if state:
                m.state = state
            if country and not m.country:
                m.country = country
            changed += 1
            break
    return changed


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    previous = fetch_previous_data(PREVIOUS_DATA_URL)
    today = date.today()

    all_meets: list[Meet] = []
    meta: dict[str, FederationMeta] = {}
    any_success = False

    for scraper_cls in ALL_SCRAPERS:
        federation = scraper_cls.federation
        logger.info("Running %s scraper", federation)
        try:
            with scraper_cls() as scraper:
                meets = scraper.scrape()
            all_meets.extend(meets)
            meta[federation] = FederationMeta(
                status="ok",
                last_successful_scrape=today,
                meet_count=len(meets),
            )
            any_success = True
            logger.info("%s: %d meets", federation, len(meets))
        except Exception as exc:
            logger.error("%s scraper failed: %s", federation, exc, exc_info=True)
            # Fall back to previous data
            fallback = get_previous_meets_for_federation(previous, federation, today)
            if fallback:
                all_meets.extend(fallback)
                prev_meta = previous.meta.get(federation) if previous else None
                meta[federation] = FederationMeta(
                    status="stale",
                    last_successful_scrape=(
                        prev_meta.last_successful_scrape if prev_meta else None
                    ),
                    meet_count=len(fallback),
                    error=str(exc),
                )
                logger.info(
                    "%s: using %d meets from previous data", federation, len(fallback)
                )
            else:
                meta[federation] = FederationMeta(
                    status="error",
                    meet_count=0,
                    error=str(exc),
                )

    if not any_success and not all_meets:
        logger.error("All scrapers failed and no previous data available")
        sys.exit(1)

    # Sort meets by date
    all_meets.sort(key=lambda m: m.date_start)

    # Deduplicate meets (same name + federation + date_start)
    seen: set[tuple[str, str, date]] = set()
    unique_meets: list[Meet] = []
    for m in all_meets:
        key = (m.name, m.federation, m.date_start)
        if key not in seen:
            seen.add(key)
            unique_meets.append(m)

    # Backfill missing state/country from the city field and meet name.
    filled = backfill_locations(unique_meets)
    if filled:
        logger.info("Backfilled location fields on %d meets", filled)

    # LLM fallback for the residue deterministic parsing can't resolve.
    geo_cache = fetch_geo_cache(GEO_CACHE_URL)
    inferred = infer_missing_locations(unique_meets, geo_cache)
    if inferred:
        logger.info("Inferred location via Gemini on %d meets", inferred)

    # Anything still without a state or a country is a genuine unknown.
    unresolved = [m for m in unique_meets if not m.state and not m.country]
    if unresolved:
        logger.warning(
            "%d meets still have no state or country: %s",
            len(unresolved),
            ", ".join(f"{m.federation}:{m.name}" for m in unresolved[:20]),
        )

    response = MeetsResponse(
        generated_at=datetime.now(timezone.utc),
        total_meets=len(unique_meets),
        meets=unique_meets,
        meta=meta,
    )

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Write events file with field names matching the old powermeet API
    # so existing WordPress snippets work without changes
    events_output = {
        "generated_at": response.generated_at.isoformat(),
        "total_meets": response.total_meets,
        "events": [
            {
                "parsed_date": m.date_start.isoformat(),
                "state": m.state or "",
                "fed": m.federation,
                "evt_name": m.name,
                # `link` is the primary meet page (info page when there is one,
                # otherwise the sign-up link) so legacy consumers always get a
                # usable link. `registration_url` is the explicit sign-up link.
                "link": str(m.url or m.registration_url or "") or "",
                "registration_url": str(m.registration_url) if m.registration_url else "",
                "venue": m.venue or "",
                "status": m.status or "active",
                "date_end": m.date_end.isoformat() if m.date_end else "",
                "equipment": m.equipment or "",
                "restrictions": m.restrictions or "",
                "city": m.city or "",
                "country": m.country or "",
                "geo_inferred": m.geo_inferred,
                "director_name": m.director_name or "",
                "director_email": m.director_email or "",
                "sanction": m.sanction or "",
                "event_type": m.event_type or "",
            }
            for m in unique_meets
        ],
        "meta": {k: v.model_dump(mode="json") for k, v in meta.items()},
    }
    events_path = OUTPUT_DIR / "events"
    events_path.write_text(
        json.dumps(events_output, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote %s (%d meets)", events_path, len(unique_meets))

    # Write meta.json separately for easy monitoring
    meta_path = OUTPUT_DIR / "meta.json"
    meta_json = {
        "generated_at": response.generated_at.isoformat(),
        "total_meets": response.total_meets,
        "federations": {k: v.model_dump() for k, v in meta.items()},
    }
    meta_path.write_text(json.dumps(meta_json, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s", meta_path)

    # Persist the geo cache alongside the output so it's published to Pages and
    # available to the next run.
    save_geo_cache(geo_cache, OUTPUT_DIR / "geo_cache.json")


if __name__ == "__main__":
    # Load GEMINI_API_KEY (and friends) from a local .env for dev runs. In CI
    # the key comes from the environment (no .env), so this is a harmless no-op.
    # Kept out of run() so importing/calling it from tests has no side effects.
    load_dotenv()
    run()
