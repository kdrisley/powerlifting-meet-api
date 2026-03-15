from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from powerlifting_meets.models import FederationMeta, Meet, MeetsResponse
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.powerlifting_america import PowerliftingAmericaScraper
from powerlifting_meets.scrapers.rps import RPSScraper
from powerlifting_meets.scrapers.usapl import USAPLScraper
from powerlifting_meets.scrapers.uspa import USPAScraper

logger = logging.getLogger(__name__)

# URL of the previously published meets.json on GitHub Pages
PREVIOUS_DATA_URL = "https://kdrisley.github.io/powerlifting-meet-api/events"

OUTPUT_DIR = Path("output")

ALL_SCRAPERS: list[type[BaseScraper]] = [
    USPAScraper,
    PowerliftingAmericaScraper,
    USAPLScraper,
    RPSScraper,
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
            meets.append(Meet(
                name=e.get("evt_name", ""),
                federation=e.get("fed", ""),
                date_start=e.get("parsed_date", ""),
                state=e.get("state") or None,
                city=e.get("city") or None,
                url=e.get("link") or None,
                venue=e.get("venue") or None,
                status=e.get("status") or None,
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
                "link": str(m.url) if m.url else "",
                "venue": m.venue or "",
                "status": m.status or "active",
                "date_end": m.date_end.isoformat() if m.date_end else "",
                "equipment": m.equipment or "",
                "restrictions": m.restrictions or "",
                "city": m.city or "",
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


if __name__ == "__main__":
    run()
