from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class PowerliftingAustraliaScraper(TribeEventsScraper):
    # Powerlifting Australia (the IPF affiliate). WordPress + Tribe Events;
    # venues carry Australian state/territory in `region` and country "Australia".
    federation = "PA-AUS"
    base_url = "https://powerliftingaustralia.com"
