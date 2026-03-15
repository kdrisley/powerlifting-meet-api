from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, HttpUrl


class Meet(BaseModel):
    name: str
    federation: str
    date_start: date
    date_end: date | None = None
    state: str | None = None
    city: str | None = None
    url: HttpUrl | None = None
    venue: str | None = None
    status: str | None = None
    equipment: str | None = None
    restrictions: str | None = None


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
