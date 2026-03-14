"""Tests for scheduler slot calculation across hour boundaries."""

from __future__ import annotations

from ai_army.scheduler import runner


def test_minute_slot_wraps_past_hour(monkeypatch) -> None:
    """Minute slots should wrap cleanly instead of raising on hour overflow."""
    monkeypatch.setattr(runner.settings, "rag_refresh_minute", 30)

    assert runner._minute_slot(45) == 15
    assert runner._hour_minute_slot(45) == (1, 15)


def test_refresh_hour_expr_offsets_interval_hours(monkeypatch) -> None:
    """Hourly expressions should shift with the wrapped slot."""
    monkeypatch.setattr(runner.settings, "rag_refresh_interval_hours", 2)

    assert runner._refresh_hour_expr(0) == "0,2,4,6,8,10,12,14,16,18,20,22"
    assert runner._refresh_hour_expr(1) == "1,3,5,7,9,11,13,15,17,19,21,23"
