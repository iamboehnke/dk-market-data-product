"""Læser det publicerede dataprodukt. Samme filer, som hjemmesidens widget bruger."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache

PRODUCT_IDS = ("fx_daily", "policy_rates_daily")
DIMENSION = {"fx_daily": "currency", "policy_rates_daily": "instrument"}


class DataUnavailable(Exception):
    pass


def _fetch(name: str) -> dict:
    base = settings.DATA_BASE_URL.rstrip("/")
    try:
        if base.startswith(("http://", "https://")):
            req = Request(f"{base}/{name}", headers={"User-Agent": "kroner-og-renter-api"})
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        return json.loads(Path(base, name).read_text(encoding="utf-8"))
    except Exception as exc:  # netværk, 404 eller ugyldig JSON
        raise DataUnavailable(f"Kunne ikke læse {name}: {exc}") from exc


def load(name: str) -> dict:
    key = f"dp:{name}"
    payload = cache.get(key)
    if payload is None:
        payload = _fetch(name)
        cache.set(key, payload)
    return payload


def manifest() -> dict:
    return load("manifest.json")


def latest() -> dict:
    return load("latest.json")


def contract(product_id: str) -> dict:
    return load(f"contracts/{product_id}.json")


def rows(product_id: str, start: date | None = None, end: date | None = None,
         codes: list[str] | None = None, limit: int | None = None) -> list[dict]:
    table = load(f"{product_id}.json")
    cols = table["columns"]
    dim = DIMENSION[product_id]
    out = []
    for values in table["rows"]:
        row = dict(zip(cols, values))
        day = date.fromisoformat(row["rate_date"])
        if start and day < start:
            continue
        if end and day > end:
            continue
        if codes and row[dim] not in codes:
            continue
        out.append(row)
    out.sort(key=lambda r: (r["rate_date"], r[dim]), reverse=True)
    return out[:limit] if limit else out
