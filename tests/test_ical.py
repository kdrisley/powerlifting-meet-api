from datetime import date

from powerlifting_meets.scrapers.ical import parse_ical

SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1@example.org
DTSTART;TZID=America/Detroit;VALUE=DATE:20260307
DTEND;TZID=America/Detroit;VALUE=DATE:20260308
URL:https://example.org/events/one/
SUMMARY:Single Day Meet
LOCATION:Some Gym\\, 1 Main St\\, Trumann\\, Arkansas\\, United States
END:VEVENT
BEGIN:VEVENT
UID:2@example.org
DTSTART;VALUE=DATE:20260620
DTEND;VALUE=DATE:20260623
SUMMARY:Multi &amp; Day\\, Event
LOCATION:Folded Venue\\, Las Vegas\\,
 NV\\, United States
END:VEVENT
END:VCALENDAR
"""


def test_parses_events_and_fields():
    events = parse_ical(SAMPLE)
    assert len(events) == 2

    a = events[0]
    assert a.uid == "1@example.org"
    assert a.summary == "Single Day Meet"
    assert a.date_start == date(2026, 3, 7)
    # DTEND is exclusive next-day for a single-day event -> collapses to None.
    assert a.date_end is None
    assert a.url == "https://example.org/events/one/"
    assert "Trumann" in a.location


def test_multiday_and_unescaping_and_folding():
    b = parse_ical(SAMPLE)[1]
    assert b.date_start == date(2026, 6, 20)
    # Inclusive last day (exclusive 06-23 -> 06-22).
    assert b.date_end == date(2026, 6, 22)
    # HTML entity and escaped comma both resolved.
    assert b.summary == "Multi & Day, Event"
    # Folded continuation line joined: "Las Vegas, NV, United States".
    assert "Las Vegas" in b.location and "NV" in b.location
