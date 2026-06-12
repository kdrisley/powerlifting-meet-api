# Feed schema

The pipeline publishes a powerlifting meet feed to GitHub Pages once a day
(6:00 UTC). This file documents the contract for consumers — including
automated agents. It is published alongside the data, so the copy next to the
feed always describes the feed it ships with.

| File | URL |
|---|---|
| Events feed | `https://kdrisley.github.io/powerlifting-meet-api/events` |
| Per-federation health | `https://kdrisley.github.io/powerlifting-meet-api/meta.json` |
| This document | `https://kdrisley.github.io/powerlifting-meet-api/SCHEMA.md` |

The feed's field names are compatible with the retired powermeet.xyz API.
**The schema is append-only**: fields are never renamed or removed; new fields
may appear. Consumers should ignore fields they don't recognize.

## `/events` — top level

```json
{
  "generated_at": "2026-06-09T06:04:12.345678+00:00",   // ISO 8601, UTC
  "total_meets": 1000,
  "events": [ ... ],                                     // sorted by parsed_date ascending
  "meta": { "<FED>": { ...same shape as meta.json federations... } }
}
```

## Event object

All values are strings unless noted. **Unknown is the empty string `""`**
(`geo_inferred` excepted — it's a boolean). An empty field means "the source
didn't say and we refused to guess" — it is never a default. Do not read
`""` in `testing_status` as "untested" or `""` in `event_type` as anything.

| Field | Meaning |
|---|---|
| `evt_name` | Meet name as published by the source (HTML-unescaped). |
| `fed` | Federation code — see the list below. |
| `parsed_date` | Start date, `YYYY-MM-DD`. Always present. |
| `date_end` | Inclusive end date for multi-day meets, else `""`. |
| `state` | **US two-letter code only** (`"TX"`). Set if and only if the meet is in the United States and the state is known. Never contains non-US regions. |
| `region` | Non-US sub-national region (`"Quebec"`, `"West Yorkshire"`, `"QLD"`). **Mutually exclusive with `state`**; when set, `country` is always set too. |
| `city` | City when known. |
| `country` | Full country name (`"United States"`, `"United Kingdom"`). US meets with a known state always have it. |
| `geo_inferred` | Boolean. `true` = city/state/region/country were filled by an LLM fallback rather than parsed from the source. Treat as lower-confidence location. |
| `venue` | Venue name or venue string from the source. |
| `link` | Primary per-meet URL: the info page when one exists, **otherwise it falls back to the registration link** so there is always a usable URL when the source provides any. |
| `registration_url` | Explicit sign-up link (registration platform, entry form) when the source distinguishes one. May equal `link`. |
| `status` | `"active"` or `"cancelled"`. |
| `equipment` | Free text derived from the meet name (`"Raw"`, `"Equipped"`, `"Raw w/ Wraps"`) when stated. |
| `restrictions` | Comma-joined entry restrictions when stated (`"Women Only, Masters"`). |
| `director_name` / `director_email` | Meet director contact when the source publishes one (a person, never a federation). |
| `sanction` | Source-provided sanction identifier, when any. |
| `event_type` | Competition format, one of `full_power`, `push_pull`, `bench_only`, `deadlift_only`, `squat_only`, or `""`. |
| `event_level` | Competitive tier, one of `LOCAL`, `STATE`, `REGIONAL`, `NATIONAL`, `INTERNATIONAL`, or `""`. Independent of `event_type`. |
| `testing_status` | `tested`, `untested`, `both` (the meet offers tested and untested divisions side by side — RPS, IPA, UKIPL, USPC, dual APF/AAPF sanctions), or `""` (unknown). |

`event_type`, `event_level`, and `testing_status` are taken from the source
when it states them, otherwise derived deterministically from the meet name
and federation; when neither yields an answer they stay `""`.

## Federation codes

Codes that appear in `fed` (one scraper each unless noted):

- **US:** `USPA`, `USAPL`, `PA` (Powerlifting America), `RPS`, `SPF`, `APF`
  (also carries international WPC meets), `PLU` (Powerlifting United),
  `ADFPF`, `USPC`, `WABDL`, `WNPF`, `IPA`, `NASA`, `100RAW`, `NPL`, `APO`,
  `MetalMilitia`
- **International:** `IPF`, `EPF` (both from the powerlifting.sport calendar),
  `IrishPF`, `CPU` (Canada), `PA-AUS` (Powerlifting Australia), `APL`
  (Australian Powerlifting League), `NZPU`, `UKIPL`, `BritishPL`, `NSF`
  (Norway), `IPL` (league internationals)
- **Via the powerlifting.com aggregator:** `WRPF`, `365Strong`, `APU`, `IPO`,
  `CAPO`, `WUAP`, `BDFPA`, `BPU`

New codes may appear as sources are added; treat the set as open.

## `meta.json` / the feed's `meta` block

One entry per **scraper source**, keyed by its monitoring code:

```json
{
  "generated_at": "...",
  "total_meets": 1000,
  "federations": {
    "USPA": {
      "status": "ok",                        // "ok" | "stale" | "error"
      "last_successful_scrape": "2026-06-09", // date or null
      "meet_count": 240,
      "error": null                           // scrape error message when not "ok"
    }
  }
}
```

- `ok` — scraped fresh this run.
- `stale` — this run's scrape failed; the feed is serving that source's meets
  from the previous publish. Meets remain valid but may be out of date.
- `error` — the scrape failed and no previous data was available; the source
  contributes 0 meets this run.

**Meta keys are scraper/source codes, not always `fed` values.** In
particular, `PLCOM` is the powerlifting.com aggregator's monitoring entry;
no event ever carries `fed: "PLCOM"` — its meets appear under the real
federation codes (`WRPF`, `365Strong`, `APU`, ...). This is expected, not an
inconsistency.

## Dedup semantics

Events are unique by `(evt_name, fed, parsed_date)`. The same physical meet
listed by two different sources/federations is *not* collapsed.
