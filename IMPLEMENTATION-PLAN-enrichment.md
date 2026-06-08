# Implementation plan — feed enrichment

Derived from `powerlifting-records/powerlifting-meet-api-improvements.md`, adjusted
to the **current** state of this scraper (audited against the live 762-meet feed in
`output/events`). Read that doc for the *why*; this is the *how*, grounded in files.

## What changed since the suggestions doc was written

The doc assumed a leaner schema than we now have. Reality check:

| Doc assumption | Actual state today |
| --- | --- |
| `director`/`sanction`/`registration_url` need new federation scraping | Already scraped & populated: `director_name` 588/762, `director_email` 544, `sanction` 238, `registration_url` 170 (USAPL + USPA) |
| `event_type` is empty, add it | `event_type` exists but is **mis-populated with event-*level*** (`LOCAL`/`STATE`/`NATIONAL`/`International`) by `usapl.py:84` and `ipf.py:98` |
| Geocoding is greenfield | True — `llm_geo.py` does *text* inference only; **zero** lat/lng anywhere. But the geo_cache→Pages→reload pattern is reusable |
| `equipment`/`restrictions` "confirm if populated" | Answered: barely (18 / 12 of 762), never rendered → safe to ignore/repurpose |
| `status` carries registration state | No — it's hardcoded `"active"` everywhere |

**Consequence:** Phase 1 is the high-value work and it starts with *untangling the
`event_type`/`event_level` collision*, not a clean green field.

## Architecture notes (where things plug in)

- All derivation happens in **`runner.py`** after dedup, alongside the existing
  `backfill_locations()` / `infer_missing_locations()` passes. Pure-transform
  enrichment is one more post-processing pass over `unique_meets` — no scraper
  touches it. This keeps per-federation scrapers dumb and the classification
  logic in one tested place.
- New derivation rules live in a new module **`classify.py`** (mirrors
  `normalize.py`: pure functions, no I/O, heavily unit-tested).
- New persisted caches (geocoding) copy the `geo_cache.json` lifecycle in
  `runner.py`: `fetch_json_cache(URL)` at start, `save_json_cache(..., OUTPUT_DIR/...)`
  at end, published to Pages.
- Feed output is the dict literal in `runner.py:388` (powermeet-compatible keys).
  Every new field is added there AND to the round-trip reader in
  `fetch_previous_data()` (`runner.py:107`) so stale-fallback meets keep the field.
- Model changes go in `models.py:Meet`.

---

## Phase 1 — Pure-transform classification (no new HTTP)

Highest value, no new dependencies. Ships `event_type`, `event_level`,
`testing_status` derived from `name` + federation.

### 1a. Resolve the `event_type` collision (do this first)

- Add `event_level: str | None` to `Meet` (`models.py`).
- Migrate the scrapers that currently dump level into `event_type`:
  - `usapl.py`: rename the "Type of Event" capture to `event_level`
    (normalize `LOCAL`/`STATE`/`NATIONAL`/`REGIONAL`/`INTERNATIONAL`).
  - `ipf.py:98`: `event_type="International"` → `event_level="INTERNATIONAL"`.
- Now `event_type` is free for its real meaning (full_power/push_pull/...).

### 1b. `classify.py` — pure functions

- `classify_event_type(name) -> str | None`: ordered keyword table. **Order matters**
  — check `bench_only`/`deadlift_only`/`push_pull` BEFORE the generic
  `powerlifting`/`full_power` fallback so "Bench Press Championship" isn't full_power.
  Values: `full_power | push_pull | bench_only | deadlift_only | squat_only`.
  Return `None` (not a guess) when no keyword hits.
- `classify_event_level(name, sanction=None) -> str | None`: keywords
  (Worlds/International → INTERNATIONAL, Nationals → NATIONAL, Regional → REGIONAL,
  State Championship → STATE, else None). Use scraped `event_level` if already set;
  only fall back to name parsing.
- `classify_testing_status(federation, name) -> str | None`: per-federation default
  map (USAPL/IPF/IPA-tested affiliates → `tested`; WRPF/SPF/RPS/APF → `untested`),
  overridden by name keywords ("Tested"/"Drug Tested" → tested, "Untested" → untested).
  For both-postures feds (USPA) → name signal only, else `None`. **Leave `None`
  rather than guess** (matches the doc's stated preference).
  - Federation defaults table is the one judgement call — seed it from the existing
    `ALL_SCRAPERS` list (20 feds) and mark uncertain ones `None`.

### 1c. Wire-up

- New pass in `runner.py` (after `backfill_locations`, before output):
  `derive_classifications(unique_meets)` that fills `event_type`, `event_level`,
  `testing_status` only when currently unset.
- Add `testing_status` to `Meet`, to the output dict (`runner.py:388`), and to the
  round-trip reader (`runner.py:107`).

### 1d. Tests

- `tests/test_classify.py`: table-driven cases per function, incl. the ordering
  traps (bench-before-full-power) and the federation-both fallback.
- Extend `test_usapl.py` / `test_ipf.py` to assert level now lands in `event_level`.

### 1e. Consumer (separate repo: `powerlifting-records`)

- Map `testing_status` / `event_type` / `event_level` in `src/lib/meets.ts`.
- Add badges + filters in `MeetsTable.astro` / `/meets/`.
- Per project rules: each new filter/toggle needs a typed `EventMap` PostHog event;
  new UI needs the accessibility pass (labels, contrast, keyboard).

**Exit gate:** event_type/level/testing populated for the bulk of the feed; filters
live on `/meets/`. Gate Phases 2-4 on whether these move the `/meets/` metrics.

---

## Phase 2 — Geocoding (lat/lng + quality)

Greenfield. Medium effort (external dep + cache + rate limit), high payoff (map +
real distance-from-you).

- Add `latitude: float | None`, `longitude: float | None`,
  `geo_quality: str | None` (`exact|approximate|none`) to `Meet`.
- New `geocode.py`: `geocode(venue, city, state, country) -> (lat, lng, quality)`.
  Query `"{venue}, {city}, {state}"`; fall back to `"{city}, {state}"`
  (→ `approximate`); else `none`.
- **Provider:** Nominatim (free, OSM) to start — 1 req/s, attribution required.
  Honor the rate limit; only geocode cache-miss rows so steady-state is ~0 calls.
- **Cache:** new `coord_cache.json`, keyed by normalized query string, using the exact
  `fetch_json_cache`/`save_json_cache` + Pages lifecycle as `geo_cache.json`.
  Add `COORD_CACHE_URL` next to `GEO_CACHE_URL` (`runner.py:45`).
- New pass `geocode_meets(unique_meets, coord_cache)` after geo inference.
- Add the three fields to output dict + round-trip reader.
- `distanceMiles` stays **client-side** (haversine from user location), not stored.
- Tests: `geocode.py` parsing/fallback with mocked HTTP (pytest-httpx, already a dep);
  cache hit/miss; rate-limit honored.

---

## Phase 3 — Federation detail enrichment (notes + level)

Most of this (director/sanction) is **already done** for USAPL/USPA. Remaining:

- `equipment_notes`, `weigh_in_notes`, `beginner_notes` — only on per-meet detail
  pages, per-federation, brittle. **Lowest priority / nice-to-have.** Scope to USAPL
  + USPA only; leave `None` elsewhere. Treat existing `equipment`/`restrictions`
  (barely populated) as superseded by these or drop them.
- `event_level` from sanction prefix (e.g. USAPL `NS-2026-04` → NATIONAL): cheap,
  fold into `classify_event_level()` in Phase 1 rather than scraping.

Only build the notes scrapers if Phase 1-2 metrics justify the maintenance cost.

---

## Phase 4 — Registration status (date-derived only)

- Add `registration_status: str | None` (`not_open_yet|open|closed`).
- **Date-derived only** — no live page checks. `closed` once meet date passes;
  `not_open_yet`/`open` from scraped open/close dates where available, else `None`.
- `registration_url` map already partly populated; a per-federation portal fallback
  map is cheap if we want coarse links for the 592 meets lacking one.
- If we ever want live status, it needs a visible freshness timestamp in the UI —
  out of scope here.

---

## Suggested order & risk

1. **Phase 1** — pure transforms, no deps, fixes the existing `event_type` data bug.
   Do this fully (incl. consumer UI) and measure before continuing.
2. **Phase 2** — geocoding, one new external dep, well-isolated, reuses cache pattern.
3. **Phase 4** — cheap date-derived registration status.
4. **Phase 3 notes** — only if justified; highest ongoing maintenance.

Each phase: model field → `classify.py`/`geocode.py` pure fn → `runner.py` pass →
output dict + round-trip reader → tests → (consumer repo) mapping + UI + PostHog + a11y.
