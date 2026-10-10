"""Tests af transform, kvalitet og en hel lokal kørsel. Kør: pytest -q"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from dataproduct import quality, transform
from dataproduct.config import Settings, load_contract
from dataproduct.run import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 9)


def _batch(product_id: str, run: str = "run1") -> pd.DataFrame:
    contract = load_contract(product_id)
    table = contract["source"]["table"].lower()
    text = (FIXTURES / run / f"{table}.csv").read_text(encoding="utf-8")
    return transform.parse_bulk(text, product_id, contract)


def test_parse_handles_decimal_comma_and_missing_marker():
    fx = _batch("fx_daily")
    assert len(fx) == 250
    eur = fx[(fx.currency == "EUR") & (fx.rate_date == date(2026, 10, 8))]
    assert eur.dkk_per_100.iloc[0] == pytest.approx(747.39)

    rates = _batch("policy_rates_daily")
    destr_last = rates[(rates.instrument == "DESNAA") & (rates.rate_date == date(2026, 10, 8))]
    assert destr_last.rate_pct.isna().all(), "'..' skal blive til en tom værdi"


def test_merge_is_idempotent():
    batch = _batch("fx_daily")
    first, _ = transform.merge_silver(None, batch, "fx_daily", "r1", "t1")
    again, stats = transform.merge_silver(first, batch, "fx_daily", "r2", "t2")
    assert len(again) == len(first)
    assert stats["inserted"] == 0 and stats["revised"] == 0
    assert stats["unchanged"] == len(batch)


def test_merge_counts_revisions_and_late_values():
    fx1, _ = transform.merge_silver(None, _batch("fx_daily"), "fx_daily", "r1", "t1")
    fx2, fx_stats = transform.merge_silver(fx1, _batch("fx_daily", "run2"), "fx_daily", "r2", "t2")
    assert fx_stats["revised"] == 1
    usd = fx2[(fx2.currency == "USD") & (fx2.rate_date == date(2026, 10, 7))]
    assert usd.dkk_per_100.iloc[0] == pytest.approx(668.75)
    assert usd.run_id.iloc[0] == "r2"

    r1, _ = transform.merge_silver(None, _batch("policy_rates_daily"), "policy_rates_daily", "r1", "t1")
    _, r_stats = transform.merge_silver(r1, _batch("policy_rates_daily", "run2"), "policy_rates_daily", "r2", "t2")
    assert r_stats["filled"] == 1, "DESTR for 8. oktober skal udfyldes ved næste kørsel"


def test_gold_change_detects_rate_hike():
    silver, _ = transform.merge_silver(None, _batch("policy_rates_daily"), "policy_rates_daily", "r1", "t1")
    gold = transform.build_gold(silver, "policy_rates_daily", {})
    hike = gold[(gold.instrument == "OFONAA") & (gold.rate_date == date(2026, 9, 11))]
    assert hike.change_bp.iloc[0] == pytest.approx(25.0)
    assert gold.rate_pct.notna().all(), "gold indeholder kun offentliggjorte værdier"


def test_quality_passes_on_real_data():
    for pid in ("fx_daily", "policy_rates_daily"):
        batch = _batch(pid)
        merged, _ = transform.merge_silver(None, batch, pid, "r1", "t1")
        results = quality.run_checks(batch, merged, load_contract(pid)["quality"], TODAY)
        summary = quality.summarize(results)
        assert not summary["blocking"], [r for r in results if not r["passed"]]


def test_quality_blocks_euro_outside_erm2_band():
    batch = _batch("fx_daily")
    batch.loc[batch.currency == "EUR", "dkk_per_100"] = 770.0
    merged, _ = transform.merge_silver(None, batch, "fx_daily", "r1", "t1")
    results = quality.run_checks(batch, merged, load_contract("fx_daily")["quality"], TODAY)
    assert quality.summarize(results)["blocking"]


def test_quality_flags_stale_data():
    batch = _batch("fx_daily")
    merged, _ = transform.merge_silver(None, batch, "fx_daily", "r1", "t1")
    results = quality.run_checks(batch, merged, load_contract("fx_daily")["quality"], date(2026, 10, 30))
    freshness = next(r for r in results if r["check"] == "freshness")
    assert not freshness["passed"] and freshness["severity"] == "error"


def _settings(tmp_path: Path, fixtures: str) -> Settings:
    return Settings(
        lake_account_url=None, public_account_url=None, public_container="public",
        public_prefix="kroner-og-renter/v1", sql_server=None, sql_database=None,
        sql_authentication="ActiveDirectoryDefault", lookback_periods=10, backfill_periods=500,
        local_dir=str(tmp_path), fixtures_dir=str(FIXTURES / fixtures),
    )


def test_end_to_end_two_runs(tmp_path):
    first = run_pipeline(_settings(tmp_path, "run1"), today=TODAY, skip_sql=True)
    assert first["status"] == "succeeded"
    assert first["products"]["fx_daily"]["periods_requested"] == 500  # backfill første gang

    second = run_pipeline(_settings(tmp_path, "run2"), today=TODAY, skip_sql=True)
    assert second["products"]["fx_daily"]["periods_requested"] == 10
    assert second["products"]["policy_rates_daily"]["merge"]["filled"] == 1

    public = tmp_path / "public" / "kroner-og-renter" / "v1"
    latest = json.loads((public / "latest.json").read_text())
    assert latest["fx"][0]["currency"] == "EUR"
    assert len(latest["fx"][0]["spark"]) == 25
    destr = next(r for r in latest["rates"] if r["instrument"] == "DESNAA")
    assert destr["date"] == "2026-10-08"

    manifest = json.loads((public / "manifest.json").read_text())
    assert [r["run_id"] for r in manifest["runs"]] == [second["run_id"], first["run_id"]]
    assert (tmp_path / "bronze" / "dst" / "dnvald").exists()


def test_failed_quality_keeps_previous_gold(tmp_path):
    run_pipeline(_settings(tmp_path, "run1"), today=TODAY, skip_sql=True)
    bad = tmp_path / "bad_fixtures"
    bad.mkdir()
    (bad / "dnrentd.csv").write_text((FIXTURES / "run2" / "dnrentd.csv").read_text())
    (bad / "dnvald.csv").write_text(
        (FIXTURES / "run2" / "dnvald.csv").read_text().replace("747,3900", "799,0000"))
    settings = _settings(tmp_path, "run2")
    settings = Settings(**{**settings.__dict__, "fixtures_dir": str(bad)})
    run = run_pipeline(settings, today=TODAY, skip_sql=True)

    assert run["status"] == "partial"
    assert run["products"]["fx_daily"]["status"] == "blocked"
    assert any((tmp_path / "silver" / "_quarantine" / "fx_daily").iterdir())
    latest = json.loads((tmp_path / "public" / "kroner-og-renter" / "v1" / "latest.json").read_text())
    eur = next(f for f in latest["fx"] if f["currency"] == "EUR")
    assert eur["dkk_per_100"] == pytest.approx(747.39), "hjemmesiden viser stadig sidste gode tal"
