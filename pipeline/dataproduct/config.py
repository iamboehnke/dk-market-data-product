"""Indstillinger læses fra miljøvariabler (App settings i Azure)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contracts"
PRODUCT_IDS = ("fx_daily", "policy_rates_daily")


def load_contract(product_id: str) -> dict:
    with open(CONTRACT_DIR / f"{product_id}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    # Datasøen (ADLS Gen2). Tom = lokal tilstand.
    lake_account_url: str | None
    # Den offentlige konto, som hjemmesiden og Django læser fra.
    public_account_url: str | None
    public_container: str
    public_prefix: str
    # Azure SQL (serving-lag). Tom = spring over.
    sql_server: str | None
    sql_database: str | None
    sql_authentication: str
    # Hvor mange perioder der hentes pr. kørsel.
    lookback_periods: int
    backfill_periods: int
    # Lokal kørsel uden Azure.
    local_dir: str | None = None
    fixtures_dir: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            lake_account_url=os.environ.get("LAKE_ACCOUNT_URL") or None,
            public_account_url=os.environ.get("PUBLIC_ACCOUNT_URL") or None,
            public_container=os.environ.get("PUBLIC_CONTAINER", "public"),
            public_prefix=os.environ.get("PUBLIC_PREFIX", "kroner-og-renter/v1"),
            sql_server=os.environ.get("SQL_SERVER") or None,
            sql_database=os.environ.get("SQL_DATABASE") or None,
            sql_authentication=os.environ.get("SQL_AUTHENTICATION", "ActiveDirectoryMSI"),
            lookback_periods=_env_int("LOOKBACK_PERIODS", 10),
            backfill_periods=_env_int("BACKFILL_PERIODS", 500),
            local_dir=os.environ.get("LOCAL_DATA_DIR") or None,
            fixtures_dir=os.environ.get("FIXTURES_DIR") or None,
        )
