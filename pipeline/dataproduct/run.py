"""Orkestrering af én kørsel: hent -> bronze -> silver -> kvalitet -> gold -> publicér -> SQL.

Kør lokalt uden Azure:
    python -m dataproduct.run --local-dir ./_local --fixtures tests/fixtures --today 2026-10-09
"""
from __future__ import annotations

import argparse
import json
import logging
import traceback
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from . import quality, sources, storage, transform
from .config import PRODUCT_IDS, Settings, load_contract

log = logging.getLogger("dataproduct")
CPH = ZoneInfo("Europe/Copenhagen")
SPARK_DAYS = 30
MANIFEST_RUNS = 30


def _stores(settings: Settings):
    if settings.local_dir:
        local = storage.LocalStore(settings.local_dir)
        return local, local
    if not (settings.lake_account_url and settings.public_account_url):
        raise RuntimeError("Sæt LAKE_ACCOUNT_URL og PUBLIC_ACCOUNT_URL, eller kør med --local-dir")
    lake = storage.BlobStore(settings.lake_account_url)
    public = storage.BlobStore(settings.public_account_url)
    return lake, public


def _latest_payload(golds: dict[str, pd.DataFrame], contracts: dict, run: dict) -> dict:
    """Det lille, hurtige svar som hjemmesidens widget læser."""
    fx = golds.get("fx_daily")
    rates = golds.get("policy_rates_daily")
    payload = {
        "product": "kroner-og-renter",
        "generated_at": run["finished_at"],
        "run_id": run["run_id"],
        "status": run["status"],
        "quality": run["quality"],
        "source": "Danmarks Nationalbank via Danmarks Statistik",
        "fx": [],
        "rates": [],
    }
    if fx is not None and not fx.empty:
        order = contracts["fx_daily"]["source"]["filters"]["VALUTA"]
        for currency in order:
            series = fx[fx["currency"] == currency].sort_values("rate_date")
            if series.empty:
                continue
            last = series.iloc[-1]
            payload["fx"].append(
                {
                    "currency": currency,
                    "name": last["currency_name"],
                    "date": last["rate_date"].isoformat(),
                    "dkk_per_100": float(last["dkk_per_100"]),
                    "dkk_per_unit": float(last["dkk_per_unit"]),
                    "change_1d_pct": None if pd.isna(last["change_1d_pct"]) else float(last["change_1d_pct"]),
                    "spark": series["dkk_per_100"].tail(SPARK_DAYS).round(4).tolist(),
                }
            )
    if rates is not None and not rates.empty:
        order = contracts["policy_rates_daily"]["source"]["filters"]["INSTRUMENT"]
        for instrument in order:
            series = rates[rates["instrument"] == instrument].sort_values("rate_date")
            if series.empty:
                continue
            last = series.iloc[-1]
            payload["rates"].append(
                {
                    "instrument": instrument,
                    "name": last["instrument_name"],
                    "date": last["rate_date"].isoformat(),
                    "rate_pct": float(last["rate_pct"]),
                    "change_bp": None if pd.isna(last["change_bp"]) else float(last["change_bp"]),
                }
            )
    return payload


def run_pipeline(settings: Settings, today: date | None = None, skip_sql: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    today = today or datetime.now(CPH).date()
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    lake, public = _stores(settings)
    prefix = settings.public_prefix

    run: dict = {
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "products": {},
    }
    contracts = {pid: load_contract(pid) for pid in PRODUCT_IDS}
    golds: dict[str, pd.DataFrame] = {}
    all_results: list[dict] = []

    for pid in PRODUCT_IDS:
        contract = contracts[pid]
        spec = transform.PRODUCTS[pid]
        silver_path = f"{pid}/{pid}.parquet"
        gold_path = f"{pid}/{pid}.parquet"
        info: dict = {"status": "running", "merge": {}, "lineage": {}}
        run["products"][pid] = info
        try:
            existing = storage.read_parquet(lake, "silver", silver_path)
            periods = settings.lookback_periods if existing is not None else settings.backfill_periods
            info["periods_requested"] = periods

            # 1. Hent og gem rådata i bronze, uændret
            if settings.fixtures_dir:
                text = sources.read_fixture(settings.fixtures_dir, contract)
            else:
                text = sources.fetch_bulk(contract, periods)
            table = contract["source"]["table"].lower()
            bronze_path = f"dst/{table}/ingest_date={today.isoformat()}/{run_id}.csv"
            info["lineage"]["bronze"] = lake.write("bronze", bronze_path, text.encode("utf-8"), "text/csv")

            # 2. Parse og merge til silver-kandidat
            batch = transform.parse_bulk(text, pid, contract)
            info["rows_from_source"] = len(batch)
            candidate, merge_stats = transform.merge_silver(existing, batch, pid, run_id, run["started_at"])
            info["merge"] = merge_stats

            # 3. Kvalitet mod kontrakten
            results = quality.run_checks(batch, candidate, contract["quality"], today)
            for r in results:
                r["product"] = pid
            all_results.extend(results)
            summary = quality.summarize(results)
            info["quality"] = summary
            info["checks"] = results

            if summary["blocking"]:
                # Karantæne: gem batchen til fejlsøgning, men rør ikke silver eller gold
                qpath = f"_quarantine/{pid}/{run_id}.parquet"
                info["lineage"]["quarantine"] = storage.write_parquet(lake, "silver", qpath, candidate)
                info["status"] = "blocked"
                previous_gold = storage.read_parquet(lake, "gold", gold_path)
                if previous_gold is not None:
                    previous_gold["rate_date"] = pd.to_datetime(previous_gold["rate_date"]).dt.date
                    golds[pid] = previous_gold
                continue

            # 4. Skriv silver og gold
            info["lineage"]["silver"] = storage.write_parquet(lake, "silver", silver_path, candidate)
            gold = transform.build_gold(candidate, pid, contract.get("labels", {}))
            info["lineage"]["gold"] = storage.write_parquet(lake, "gold", gold_path, gold)
            info["rows_gold"] = len(gold)
            golds[pid] = gold

            # Den del af gold, der kan være ændret i denne kørsel (incl. dagen før,
            # fordi ændringen beregnes ud fra den)
            window_start = min(batch["rate_date"]) - timedelta(days=7)
            info["changed_window_start"] = window_start.isoformat()

            # 5. Publicér historik og kontrakt til forbrugerne
            info["lineage"]["public_history"] = storage.write_json(
                public, settings.public_container, f"{prefix}/{pid}.json",
                {"product": pid, "run_id": run_id, **transform.to_columnar(gold.drop(columns=["run_id"]))},
                cache_seconds=600,
            )
            storage.write_json(public, settings.public_container, f"{prefix}/contracts/{pid}.json",
                               contract, cache_seconds=3600)
            info["status"] = "published"
        except Exception as exc:  # én fejlende kilde må ikke vælte resten
            log.exception("Produkt %s fejlede", pid)
            info["status"] = "failed"
            info["error"] = f"{type(exc).__name__}: {exc}"
            info["traceback"] = traceback.format_exc(limit=3)

    statuses = {p["status"] for p in run["products"].values()}
    run["quality"] = quality.summarize(all_results)
    run["status"] = ("succeeded" if statuses == {"published"}
                     else "failed" if statuses <= {"failed"} else "partial")

    # 6. Indlæs i Azure SQL (sidst, så en sovende database ikke forsinker hjemmesiden)
    run["sql"] = {"status": "skipped"}
    if not skip_sql and settings.sql_server and settings.sql_database:
        try:
            from .sql import GOLD_TABLES, SqlLoader

            with SqlLoader(settings.sql_server, settings.sql_database, settings.sql_authentication) as db:
                loaded = {}
                for pid, info in run["products"].items():
                    if info["status"] == "published":
                        gold = golds[pid]
                        since = date.fromisoformat(info["changed_window_start"])
                        loaded[pid] = db.merge_gold(pid, gold[gold["rate_date"] >= since])
                        info["lineage"]["sql"] = f"{settings.sql_database}.{GOLD_TABLES[pid]['table']}"
                run["sql"] = {"status": "loaded", "rows": loaded}
                run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                run["details_json"] = json.dumps(
                    {pid: {k: v for k, v in i.items() if k != "checks"} for pid, i in run["products"].items()},
                    default=str)[:3900]
                db.log_run(run)
        except Exception as exc:
            log.exception("SQL-indlæsning fejlede")
            run["sql"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            if run["status"] == "succeeded":
                run["status"] = "partial"

    run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run.pop("details_json", None)

    # 7. Kørselslog i søen og manifest til kataloget (publiceres altid, også ved fejl)
    storage.write_json(lake, "gold", f"_runs/{today.isoformat()}/{run_id}.json", run)
    manifest = storage.read_json(public, settings.public_container, f"{prefix}/manifest.json") or {}
    runs = [_run_summary(run)] + manifest.get("runs", [])
    manifest = {
        "product": "kroner-og-renter",
        "updated_at": run["finished_at"],
        "products": {
            pid: {
                "id": pid,
                "name": c["name"],
                "version": c["version"],
                "domain": c["domain"],
                "owner": c["owner"],
                "description": c["description"].strip(),
                "source": c["source"]["system"] + ", tabel " + c["source"]["table"],
                "status": run["products"][pid]["status"],
                "latest_date": (golds[pid]["rate_date"].max().isoformat() if pid in golds else None),
                "rows": int(len(golds[pid])) if pid in golds else 0,
                "checks": run["products"][pid].get("checks", []),
                "lineage": run["products"][pid].get("lineage", {}),
                "consumers": c.get("consumers", []),
            }
            for pid, c in contracts.items()
        },
        "runs": runs[:MANIFEST_RUNS],
    }
    storage.write_json(public, settings.public_container, f"{prefix}/manifest.json", manifest, cache_seconds=300)
    if golds:
        storage.write_json(public, settings.public_container, f"{prefix}/latest.json",
                           _latest_payload(golds, contracts, run), cache_seconds=300)
    log.info("Kørsel %s: %s", run_id, run["status"])
    return run


def _run_summary(run: dict) -> dict:
    return {
        "run_id": run["run_id"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "status": run["status"],
        "quality": run["quality"],
        "sql": run["sql"]["status"],
        "products": {
            pid: {"status": i["status"], "merge": i.get("merge", {}), "error": i.get("error")}
            for pid, i in run["products"].items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Kør kroner-og-renter-pipelinen")
    parser.add_argument("--local-dir", help="Skriv til en lokal mappe i stedet for Azure")
    parser.add_argument("--fixtures", help="Læs kilde-CSV fra en mappe i stedet for API'et")
    parser.add_argument("--today", help="Overstyr dags dato (YYYY-MM-DD), nyttigt til test")
    parser.add_argument("--skip-sql", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = Settings.from_env()
    if args.local_dir or args.fixtures:
        settings = Settings(**{**settings.__dict__,
                               "local_dir": args.local_dir or settings.local_dir,
                               "fixtures_dir": args.fixtures or settings.fixtures_dir})
    today = date.fromisoformat(args.today) if args.today else None
    run = run_pipeline(settings, today=today, skip_sql=args.skip_sql)
    print(json.dumps(_run_summary(run), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
