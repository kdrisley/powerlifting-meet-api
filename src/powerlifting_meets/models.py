from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, HttpUrl


class Meet(BaseModel):
    name: str
    federation: str
    date_start: date
    date_end: date | None = None
    # `state` is a US two-letter code ONLY (set iff the meet is in the US).
    # `region` is the non-US sub-national region (e.g. "QLD", "Ontario"); it is
    # set only for non-US meets, and `country` is always populated when it is.
    # The two are mutually exclusive so US filters on `state` stay clean.
    state: str | None = None
    region: str | None = None
    city: str | None = None
    country: str | None = None
    # True when city/state/country were filled by the LLM fallback rather than
    # parsed from the source, so consumers can tell inferred values apart.
    geo_inferred: bool = False
    url: HttpUrl | None = None
    registration_url: HttpUrl | None = None
    venue: str | None = None
    status: str | None = None
    equipment: str | None = None
    restrictions: str | None = None
    director_name: str | None = None
    director_email: str | None = None
    sanction: str | None = None
    # `event_type` is the competition format derived from the meet name
    # (full_power | push_pull | bench_only | deadlift_only | squat_only).
    # `event_level` is the competitive tier (LOCAL | STATE | REGIONAL |
    # NATIONAL | INTERNATIONAL). The two are independent and were previously
    # conflated — some scrapers used to write level values into event_type.
    event_type: str | None = None
    event_level: str | None = None
    # `tested` | `untested` when derivable from federation + name, else None
    # (we leave it null rather than guess for both-posture federations).
    testing_status: str | None = None


class FederationMeta(BaseModel):
    status: str  # "ok", "stale", "error"
    last_successful_scrape: date | None = None
    meet_count: int = 0
    error: str | None = None


class MeetsResponse(BaseModel):
    generated_at: datetime
    total_meets: int
    meets: list[Meet]
    meta: dict[str, FederationMeta] = {}
