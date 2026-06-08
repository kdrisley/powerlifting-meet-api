"""A small, dependency-free iCalendar (RFC 5545) VEVENT reader.

Only the bits we need to turn a public `.ics` feed into meets: line unfolding,
per-property parameter handling, text unescaping, and DATE/DATE-TIME parsing.
Used by the WABDL scraper, whose site exposes an Events Manager iCal feed.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass
class ICalEvent:
    uid: str | None
    summary: str | None
    location: str | None
    url: str | None
    date_start: date
    date_end: date | None


def _unfold(text: str) -> list[str]:
    """Join RFC 5545 folded lines (continuations begin with a space or tab)."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    """Reverse RFC 5545 text escaping, then resolve HTML entities."""
    out = (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )
    return html.unescape(out).strip()


def _split_prop(line: str) -> tuple[str, dict[str, str], str] | None:
    """Split "NAME;PARAM=v:VALUE" into (name, params, value)."""
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v
    return name, params, value


def _parse_dt(value: str, params: dict[str, str]) -> date | None:
    """Parse a DTSTART/DTEND value to a date (date-only or datetime)."""
    v = value.strip()
    if params.get("VALUE") == "DATE" or len(v) == 8:
        try:
            return datetime.strptime(v[:8], "%Y%m%d").date()
        except ValueError:
            return None
    # DATE-TIME, possibly UTC ("...Z") or floating/local; we only need the date.
    try:
        return datetime.strptime(v[:8], "%Y%m%d").date()
    except ValueError:
        return None


def parse_ical(text: str) -> list[ICalEvent]:
    """Parse all VEVENTs from an iCalendar document.

    DTEND for all-day events is exclusive per the spec, so a single-day event
    has DTEND = DTSTART + 1 day; we collapse that back to `date_end = None` and
    treat a true multi-day span as the inclusive last day.
    """
    events: list[ICalEvent] = []
    cur: dict | None = None
    dtend_raw: date | None = None

    for line in _unfold(text):
        upper = line.strip().upper()
        if upper == "BEGIN:VEVENT":
            cur = {}
            dtend_raw = None
            continue
        if upper == "END:VEVENT":
            if cur is not None and cur.get("date_start") is not None:
                start = cur["date_start"]
                end = dtend_raw
                if end is not None:
                    end = end - timedelta(days=1)  # exclusive -> inclusive
                    if end <= start:
                        end = None
                events.append(
                    ICalEvent(
                        uid=cur.get("uid"),
                        summary=cur.get("summary"),
                        location=cur.get("location"),
                        url=cur.get("url"),
                        date_start=start,
                        date_end=end,
                    )
                )
            cur = None
            continue
        if cur is None:
            continue

        parsed = _split_prop(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "UID":
            cur["uid"] = value.strip()
        elif name == "SUMMARY":
            cur["summary"] = _unescape(value) or None
        elif name == "LOCATION":
            cur["location"] = _unescape(value) or None
        elif name == "URL":
            cur["url"] = value.strip() or None
        elif name == "DTSTART":
            cur["date_start"] = _parse_dt(value, params)
        elif name == "DTEND":
            dtend_raw = _parse_dt(value, params)

    return events
