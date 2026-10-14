from datetime import UTC, date, datetime

import pytest

from imgsr.db.models import UsageDaily
from imgsr.quota import QuotaExceeded, consume, count_llm, refund, today, used

DAY = date(2026, 10, 14)


def test_consume_increments_all_subjects(sf):
    with sf() as db:
        charge = consume(db, [("ip:1.1.1.1", 3, "ip"), ("guest:global", 100, "global")], DAY)
        assert charge == {"date": "2026-10-14", "subjects": ["ip:1.1.1.1", "guest:global"]}
        assert used(db, "ip:1.1.1.1", DAY) == 1
        assert used(db, "guest:global", DAY) == 1


def test_consume_rejects_without_partial_increment(sf):
    with sf() as db:
        for _ in range(2):
            consume(db, [("guest:global", 2, "global")], DAY)
        with pytest.raises(QuotaExceeded, match="global"):
            consume(db, [("ip:2.2.2.2", 3, "ip"), ("guest:global", 2, "global")], DAY)
        assert used(db, "ip:2.2.2.2", DAY) == 0
        assert used(db, "guest:global", DAY) == 2


def test_refund_never_goes_negative(sf):
    with sf() as db:
        charge = consume(db, [("user:1", 5, "u")], DAY)
        refund(db, charge)
        refund(db, charge)
        refund(db, None)
        assert used(db, "user:1", DAY) == 0


def test_count_llm(sf):
    with sf() as db:
        count_llm(db, "user:1", DAY)
        count_llm(db, "user:1", DAY)
        assert db.get(UsageDaily, ("user:1", DAY)).llm_calls == 2


def test_today_uses_utc_plus_8():
    assert today(datetime(2026, 10, 13, 16, 30, tzinfo=UTC)) == date(2026, 10, 14)
    assert today(datetime(2026, 10, 13, 15, 59, tzinfo=UTC)) == date(2026, 10, 13)
