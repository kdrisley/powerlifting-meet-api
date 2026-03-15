from datetime import date, datetime, timezone

from powerlifting_meets.models import FederationMeta, Meet, MeetsResponse


class TestMeet:
    def test_minimal_meet(self):
        meet = Meet(name="Test Meet", federation="USPA", date_start=date(2026, 5, 1))
        assert meet.name == "Test Meet"
        assert meet.federation == "USPA"
        assert meet.date_start == date(2026, 5, 1)
        assert meet.date_end is None
        assert meet.state is None

    def test_full_meet(self):
        meet = Meet(
            name="Big Meet",
            federation="USAPL",
            date_start=date(2026, 6, 1),
            date_end=date(2026, 6, 2),
            state="TX",
            city="Houston",
            url="https://example.com/meet",
            venue="Convention Center",
            status="active",
            equipment="Raw",
            restrictions="Women Only",
        )
        assert meet.state == "TX"
        assert meet.city == "Houston"
        assert meet.equipment == "Raw"


class TestMeetsResponse:
    def test_serialization_roundtrip(self):
        response = MeetsResponse(
            generated_at=datetime(2026, 3, 14, tzinfo=timezone.utc),
            total_meets=1,
            meets=[
                Meet(name="Test", federation="RPS", date_start=date(2026, 4, 1)),
            ],
            meta={
                "RPS": FederationMeta(
                    status="ok",
                    last_successful_scrape=date(2026, 3, 14),
                    meet_count=1,
                ),
            },
        )
        json_str = response.model_dump_json()
        loaded = MeetsResponse.model_validate_json(json_str)
        assert loaded.total_meets == 1
        assert loaded.meets[0].name == "Test"
        assert loaded.meta["RPS"].status == "ok"
