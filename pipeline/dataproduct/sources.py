"""Henter data fra Statistikbankens åbne API (ingen nøgle nødvendig)."""
from __future__ import annotations

import time
from pathlib import Path

import requests

API_URL = "https://api.statbank.dk/v1/data"


def fetch_bulk(contract: dict, periods: int, retries: int = 3) -> str:
    """Returnerer det rå semikolonseparerede svar for de seneste `periods` bankdage.

    `(-n+N)` er Statistikbankens udtryk for "de seneste N perioder". Vi henter
    altid et overlap på flere dage, så sene eller rettede tal kommer med næste
    gang, og merge-trinnet sørger for, at intet bliver dubleret.
    """
    source = contract["source"]
    variables = [{"code": code, "values": values} for code, values in source["filters"].items()]
    variables.append({"code": "Tid", "values": [f"(-n+{periods})"]})
    body = {
        "table": source["table"],
        "format": "BULK",
        "lang": "da",
        "valuePresentation": "Code",
        "variables": variables,
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(API_URL, json=body, timeout=60)
            response.raise_for_status()
            text = response.content.decode("utf-8-sig")
            if not text.strip():
                raise ValueError("Tomt svar fra Statistikbanken")
            return text
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Kunne ikke hente {source['table']}: {last_error}") from last_error


def read_fixture(fixtures_dir: str, contract: dict) -> str:
    """Bruges til test og lokal kørsel uden netværk."""
    path = Path(fixtures_dir) / f"{contract['source']['table'].lower()}.csv"
    return path.read_text(encoding="utf-8")
