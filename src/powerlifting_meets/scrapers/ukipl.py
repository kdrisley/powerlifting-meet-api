from __future__ import annotations

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import resolve_location
from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class UKIPLScraper(TribeEventsScraper):
    """UK IPL affiliate (powerliftingukipl.org), a Tribe Events site.

    The calendar mixes domestic UK meets with IPL international championships
    (Italy, Las Vegas) that belong to other feeds — US IPL events are already on
    the USPA calendar. Keep UK meets only: an event is dropped when its venue
    country, or a country resolved from the title when the venue is empty, is
    non-UK. Domestic meets with no location signal at all are stamped United
    Kingdom (single-country federation), so they never need geo inference.
    """

    federation = "UKIPL"
    base_url = "https://powerliftingukipl.org"

    def _parse_event(self, event: dict) -> Meet | None:
        meet = super()._parse_event(event)
        if meet is None:
            return None

        country = meet.country
        if not country:
            # No venue on the event; internationals state the country in the
            # title (e.g. "IPL EUROPEAN CHAMPIONSHIPS, ITALY").
            _, _, country = resolve_location(meet.name)

        if country and country != "United Kingdom":
            return None
        if not meet.country:
            meet.country = "United Kingdom"
        return meet
