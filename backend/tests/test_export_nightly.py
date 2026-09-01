"""Tests for the nightly screen export (pipeline stage ``export_screens``).

The interesting behaviour is not that files get written. It is that a screen
which returned rows yesterday and none today leaves NO file behind: a stale
export that reads as current is the failure mode this project treats as its
most dangerous (FR-8.9), and a shared file is read by someone with no way to
tell.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from alpha500 import exports
from alpha500.config import settings

AS_OF = date(2026, 9, 1)


@pytest.fixture
def out_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(settings, "export_dir", tmp_path / "exports", raising=False)
    return tmp_path / "exports" / "latest"


def fake_presets(monkeypatch, rows_by_screen: dict[str, int]) -> None:
    """Stub the screen registry and its runner, so the test owns the outcome."""
    presets = {
        name: {"name": name, "filters": {"op": "AND", "conditions": []}}
        for name in rows_by_screen
    }
    monkeypatch.setattr("alpha500.screens.presets.PRESETS", presets, raising=False)

    def run(_conn, definition, _as_of):
        count = rows_by_screen[definition["name"]]
        if count < 0:
            raise RuntimeError("screen blew up")
        return [
            {"tradingsymbol": f"SYM{i}", "name": f"Company {i}", "close": 100.0 + i}
            for i in range(count)
        ]

    monkeypatch.setattr("alpha500.screens.filter_engine.run_screen", run, raising=False)


def files(out_dir: Path) -> set[str]:
    return {p.name for p in out_dir.glob("*.html")}


def test_writes_one_stable_file_per_non_empty_screen(out_dir, monkeypatch):
    """Stable names, so there is always one current file rather than a year
    of accumulated snapshots to pick through."""
    fake_presets(monkeypatch, {"Momentum Leaders": 3, "Trend Template": 5})
    summary = exports.export_nightly(None, AS_OF)

    assert sorted(summary["written"]) == ["Momentum Leaders", "Trend Template"]
    assert files(out_dir) == {"momentum_leaders.html", "trend_template.html"}
    # No timestamp in the name: tomorrow overwrites rather than accumulates.
    assert not any(char.isdigit() for char in "".join(files(out_dir)))


def test_an_empty_screen_writes_no_file(out_dir, monkeypatch):
    fake_presets(monkeypatch, {"Momentum Leaders": 2, "Volatility Contraction": 0})
    summary = exports.export_nightly(None, AS_OF)

    assert summary["skipped"] == ["Volatility Contraction"]
    assert files(out_dir) == {"momentum_leaders.html"}


def test_yesterdays_file_does_not_survive_a_screen_going_empty(out_dir, monkeypatch):
    """The point of the whole stage.

    Left in place, that file would be read tomorrow as today's result, with
    nothing on screen to say otherwise.
    """
    fake_presets(monkeypatch, {"Momentum Leaders": 2, "Approaching High": 4})
    exports.export_nightly(None, AS_OF)
    assert "approaching_high.html" in files(out_dir)

    # Next session: Approaching High finds nothing.
    fake_presets(monkeypatch, {"Momentum Leaders": 2, "Approaching High": 0})
    exports.export_nightly(None, date(2026, 9, 2))

    assert "approaching_high.html" not in files(out_dir)
    assert files(out_dir) == {"momentum_leaders.html"}


def test_a_rerun_refreshes_rather_than_duplicates(out_dir, monkeypatch):
    fake_presets(monkeypatch, {"Momentum Leaders": 2})
    exports.export_nightly(None, AS_OF)
    exports.export_nightly(None, AS_OF)
    assert files(out_dir) == {"momentum_leaders.html"}


def test_one_broken_screen_does_not_lose_the_others(out_dir, monkeypatch):
    """A single bad preset must not cost the rest of the night's exports."""
    fake_presets(monkeypatch, {"Good One": 2, "Broken": -1, "Also Good": 3})
    summary = exports.export_nightly(None, AS_OF)

    assert sorted(summary["written"]) == ["Also Good", "Good One"]
    assert len(summary["failed"]) == 1 and "Broken" in summary["failed"][0]
    assert files(out_dir) == {"good_one.html", "also_good.html"}


def test_the_export_is_self_contained_and_carries_its_as_of(out_dir, monkeypatch):
    """A reviewer opening this offline must still see which session it is."""
    fake_presets(monkeypatch, {"Momentum Leaders": 2})
    exports.export_nightly(None, AS_OF)

    body = (out_dir / "momentum_leaders.html").read_text(encoding="utf-8")
    assert "2026-09-01" in body, "provenance must name the session"
    assert "http://" not in body and "https://" not in body, "must load nothing remote"


def test_timestamped_on_demand_exports_are_left_alone(out_dir, monkeypatch):
    """The UI's FR-9.7 exports live in exports/, not exports/latest."""
    ad_hoc = settings.export_dir / "momentum_leaders_20260825_220021.html"
    ad_hoc.parent.mkdir(parents=True, exist_ok=True)
    ad_hoc.write_text("an earlier one-off", encoding="utf-8")

    fake_presets(monkeypatch, {"Momentum Leaders": 2})
    exports.export_nightly(None, AS_OF)

    assert ad_hoc.read_text(encoding="utf-8") == "an earlier one-off"
