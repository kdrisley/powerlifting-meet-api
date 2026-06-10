# Implementation plan: new sources, deterministic-only

Scope: add the discovery-sweep sources (June 2026) that can be scraped AND verified as
unique without the LLM tier. Rule of thumb applied throughout:

- **Parsing**: structured endpoint (JSON/ICS/JSON-LD) or stable server-rendered HTML only.
  No `LLMExtractionScraper` subclasses in this plan.
- **Uniqueness**: every source is either a sanctioning body we don't scrape anywhere else
  (inherently unique meets), or has a deterministic rule that excludes the overlapping
  slice. No similarity matching, no model calls.
- **Geo**: single-country federations stamp `country` (and parse city/region from
  structured fields) in the scraper so meets don't fall through to the Gemini geo
  fallback. The LLM geo tier remains as a safety net but should see ~0 new meets.

Deliberately EXCLUDED for needing LLM interpretation: LiftingCast (location only in
free-text names), WRPF UK (year-less free text), BVDK (brittle RSC payload), 365
Strong / Metal Militia HTML fallback path (only included below via their structured
warmupData JSON, with a verify-first gate), UPA/APA (dates in post titles, low yield).

Each phase = one branch/PR. Per-source work follows `.claude/skills/new-meet-source/SKILL.md`
(fixture from a real capture, `scraper_runner` tests, register in `ALL_SCRAPERS`,
full-runner verification, meta.json check).

---

## Phase 1 — Tribe Events subclasses (trivial)

### 1a. NPL — National Powerlifting League
- Endpoint (verified): `https://npleague.net/wp-json/tribe/events/v1/events` — 21 events,
  venue city/state, per-meet URLs.
- Scraper: `npl.py`, subclass `TribeEventsScraper`, `federation = "NPL"`,
  `base_url = "https://npleague.net"`. Likely zero overrides.
- Uniqueness: own sanctioning body, US — not listed by any current source.
- Tests: fixture `npl_tribe.json` (capture 3–5 events incl. one with venue address
  fallback); standard Tribe-subclass assertions (see `test_tribe_subclasses.py`).
- Yield: ~20–30 meets/yr. Effort: ~30 min.

### 1b. UKIPL
- Endpoint (verified): `https://powerliftingukipl.org/wp-json/tribe/events/v1/events` —
  8 upcoming, venues, per-event URLs.
- Scraper: `ukipl.py`, subclass `TribeEventsScraper`, `federation = "UKIPL"`.
- Geo: venues are UK; Tribe venue country normalization already handles this, but add a
  post-parse guard: if neither state nor country resolved, set `country = "United Kingdom"`
  (override `_parse_event` or post-process in `scrape()`).
- Uniqueness vs existing feds: none of our 20 feds list UK IPL meets.
- Uniqueness vs Phase 2a (IPL ICS): **deterministic split — UKIPL scraper keeps only
  UK-located events; the IPL ICS scraper carries internationals.** UKIPL's calendar
  re-lists IPL European/World champs; drop UKIPL events whose venue country is not UK.
- Tests: fixture `ukipl_tribe.json`; include one international event to prove the drop rule.
- Yield: ~10–20 meets/yr. Effort: ~45 min.

## Phase 2 — Structured feeds (ICS, JSON-LD)

### 2a. IPL international
- Endpoint (verified): public Google Calendar ICS
  `https://calendar.google.com/calendar/ical/of0ufu6t86cngkn3278f8bqi0c%40group.calendar.google.com/public/basic.ics`
  — 317 VEVENTs (mostly historical), ~12 upcoming with SUMMARY + LOCATION + DTSTART.
- Scraper: `ipl.py`, subclass `BaseScraper`, reuse `scrapers/ical.py` reader (the WABDL
  pattern). Filter `date_start >= today`. Parse LOCATION with `resolve_location()` /
  `normalize_country()`.
- Uniqueness rules (both deterministic):
  - **Drop US-located events** — US IPL meets (IPL Worlds/Olympia in Las Vegas) appear on
    the USPA calendar we already scrape (USPA is the IPL US affiliate).
  - UK events stay here only if Phase 1b's UK-only rule is in place (no conflict: this
    feed's UK events are internationals UKIPL also lists — to be safe, also drop
    UK-located events here IF UKIPL is shipped; decide final ownership in the PR).
- Geo: LOCATION strings are "City, Country" — deterministic via `resolve_location`.
- Tests: fixture `ipl_calendar.ics` (trim to ~6 VEVENTs: one past, one US, one UK, three
  keepers). Assert the drop rules.
- Yield: ~15–25 meets/yr after filtering. Effort: ~1–2 h.

### 2b. APO — American Powerlifting Organization
- Endpoint (verified): JSON-LD `Event` blocks server-rendered on
  `https://apopowerlifting.com/events/` (Modern Events Calendar; note
  `wp-json/mec/v1/events` exists but returns `[]` — do not use it).
- Scraper: `apo.py`, subclass `BaseScraper`; parse `<script type="application/ld+json">`
  blocks (same family as `cpu.py`). Fields: name, ISO startDate, venue, per-meet URL.
- Implementation-time check: confirm JSON-LD `location` includes address/city/state; if it
  is venue-name-only, parse city/state from the venue string with
  `parse_address_location()`; meets still lacking a state get `country = "United States"`
  (APO is US-only) so nothing reaches the LLM geo tier.
- Uniqueness: own (equipped/multi-ply) sanctioning body, not covered anywhere.
- Tests: fixture `apo_events.html` (the events page trimmed to its JSON-LD blocks).
- Yield: ~10–15 meets/yr. Effort: ~1–2 h.

## Phase 3 — Server-rendered HTML (lxml)

### 3a. British Powerlifting
- Pages (verified, anti-bot gone, plain WordPress SSR):
  - `https://www.britishpowerlifting.org/upcoming-championships/` — divisional cards
  - `https://www.britishpowerlifting.org/upcoming-events-competitions/` — majors
  - Cards: `a.content_row_card` with a `date_container` ("10 Oct - 11 Oct, 2026"),
    title, level taxonomy, per-meet URL (`/championship/<slug>/`, `/event/<slug>/`).
  - Do NOT use `/calendar` (redirects to a news post) or the WP REST CPTs
    (`wp/v2/event|championship` exist but expose no dates).
- Scraper: `british_pl.py`, subclass `BaseScraper`, scrape both listing pages, parse the
  "D Mon - D Mon, YYYY" range into date_start/date_end.
- Geo: stamp `country = "United Kingdom"` on every meet (single-country fed). Region/city
  often absent from cards — leave None rather than guess (honest-null house rule); the
  feed stays filterable by country. **Explicitly do not rely on geo inference.**
- Registration: per-meet pages say "How to Enter" via Sport80; set
  `registration_url = "https://britishpowerlifting.sport80.com/"` only if the meet page is
  fetched — for v1, leave registration_url None and let `url` (the meet page) carry it.
- Uniqueness: IPF affiliate, but national/divisional meets do NOT appear on
  powerlifting.sport (verified — that calendar is internationals only). No rule needed.
- Tests: fixture pages for both listings; assert date-range parsing and country stamp.
- Yield: ~25–40 meets/yr. Effort: ~2–3 h.

### 3b. NSF Norway (optional in this phase — international, decide on audience value)
- Page (verified): `https://styrkeloft.no/terminliste/` — server-rendered table, 191 rows
  for 2026; month section headers + columns Dato/Stevne/Type/Arrangør/Sted; per-meet
  entry-list links (`resultatservice?nsf_page=pameldingsliste&id=N`).
- Scraper: `nsf.py`, subclass `BaseScraper`. Date = day from Dato + month from section
  header + year from page heading (same implied-year pattern as `apf.py`).
- **Filter Type deterministically**: keep open meet types (Åpent, NM, regionals), drop
  `Klubbstevne` rows (in-house club nights, ~70% of rows, no outside registration).
- Geo: `city = Sted`, `country = "Norway"`, region None.
- Uniqueness: IPF affiliate; nationals not on powerlifting.sport. No overlap.
- Tests: fixture `nsf_terminliste.html` trimmed to two month sections incl. klubbstevne
  rows to prove the filter.
- Yield: ~40–60 meets/yr after filtering. Effort: ~2–3 h.

## Phase 4 — Wix warmupData (verify-first gate)

**GATE OUTCOME (2026-06-09):** Metal Militia PASSED — its warmup-data carries fully
structured Wix Events records (title, ISO + venue-local formatted dates, geocoded
fullAddress, external JotForm registration links, slug for per-meet URLs). Shipped as
`metal_militia.py`. 365 Strong FAILED on every criterion: warmup-data is an empty 2KB
stub, events are free-text blocks in the page body, and there are **no per-meet URLs and
no registration links at all** — so it fails the feed's URL requirement even via the LLM
tier. Dropped; recheck only if the site adds the Wix Events app or per-meet pages.

### 4a. Metal Militia + 4b. 365 Strong (original gate)
- Both sites are Wix but server-render their event lists, and the HTML embeds the Wix
  Events app's `warmupData` JSON (verified present; **contents not yet audited**).
- Gate: before building, capture the page and confirm `warmupData` contains the full
  schedule as structured JSON (title, ISO dates, location object, registration link). If
  yes → deterministic JSON parse out of the HTML (`json.loads` on the embedded blob), one
  scraper each (`metal_militia.py`, `strong365.py`), US-only so `country` stamping +
  `parse_address_location` cover geo.
- If warmupData turns out partial/JS-hydrated → **stop; these fall to the LLM tier and
  are out of scope for this plan.** (Do not regex free text off Wix pages.)
- Uniqueness: own sanctioning bodies (Metal Militia; 365 Strong WPF) — not covered.
- Yield: ~10–20 meets/yr each. Effort: ~1 h gate + ~2 h each if green.

## Phase 5 — powerlifting.com aggregator (deterministic allowlist)

- Endpoint (verified): `https://powerlifting.com/wp-json/tribe/events/v1/events` — 534
  upcoming, `organizer` = federation name, `website` = registration link,
  `categories` = event type, but mixed with strongman and with feds we already scrape.
- Deterministic uniqueness via **organizer allowlist**: maintain an explicit
  `ORGANIZER_TO_FED` map containing ONLY federations we don't scrape directly
  (e.g. "World Raw Powerlifting Federation" → WRPF, "WUAP" → WUAP). Emit a meet iff its
  organizer is in the map; drop everything else (covered feds, strongman, unknown
  organizers). Unknowns are logged (`log unmatched organizers`) so the map can grow by
  review, never by guessing.
- This is the only deterministic WRPF coverage path found (thewrpf.com is parked).
- Scraper: `powerlifting_com.py`, subclass `TribeEventsScraper` with `_parse_event`
  override for the organizer gate + per-meet `Meet.federation` from the map; class
  `federation = "PLCOM"` is just the meta.json/fallback key (aggregator pattern — see
  skill). Venue city sometimes munges "City ST" into one field —
  `parse_address_location` handles it.
- Tests: fixture with a WRPF event (kept), a USAPL event (dropped), a strongman event
  (dropped), an unknown organizer (dropped + would-log).
- Yield: starts small (allowlist begins with WRPF/WUAP, grows by review). Effort: ~3–4 h.

---

## Sequencing & verification

| PR | Sources | New meets/yr (est.) |
|----|---------|---------------------|
| 1 | NPL, UKIPL | ~35 |
| 2 | IPL ICS, APO | ~30 |
| 3 | British Powerlifting (+ NSF Norway if wanted) | ~30 (+50) |
| 4 | Metal Militia, 365 Strong (gated) | ~25 |
| 5 | powerlifting.com allowlist | ~20+, grows |

Per PR: pytest + ruff, live single-scraper run eyeballed, full `runner` run checking (a)
new fed(s) `"status": "ok"` in `output/meta.json`, (b) the "no state or country" warning
count does not grow (proves the no-LLM geo goal), (c) Gemini call counts in logs stay at
baseline. Feed schema untouched (append-only contract with liftvault.com).
