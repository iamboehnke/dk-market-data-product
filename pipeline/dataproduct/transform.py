"""Rene funktioner for bronze -> silver -> gold.

Ingen I/O her, så alt kan testes lokalt. Logikken svarer 1:1 til det, man
ville skrive i en Databricks-notebook: parse, MERGE på nøgle, beregn gold.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ProductSpec:
    source_dim: str     # kolonnen i Statistikbanken, fx VALUTA
    dim: str            # vores navn, fx currency
    value: str          # vores værdikolonne, fx dkk_per_100

    @property
    def key(self) -> list[str]:
        return ["rate_date", self.dim]


PRODUCTS: dict[str, ProductSpec] = {
    "fx_daily": ProductSpec(source_dim="VALUTA", dim="currency", value="dkk_per_100"),
    "policy_rates_daily": ProductSpec(source_dim="INSTRUMENT", dim="instrument", value="rate_pct"),
}


def parse_tid(values: pd.Series) -> pd.Series:
    """'2026M10D08' -> 2026-10-08."""
    return pd.to_datetime(values.astype(str), format="%YM%mD%d").dt.date


def parse_bulk(text: str, product_id: str, contract: dict) -> pd.DataFrame:
    """Bronze-tekst -> typet batch med én række pr. dato og dimension.

    Statistikbanken bruger decimalkomma og '..' for værdier, der endnu ikke er
    offentliggjort. Dem gør vi til NaN og lader kvalitetstjekket tage stilling.
    """
    spec = PRODUCTS[product_id]
    missing = contract["source"].get("missing_marker", "..")
    raw = pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False)
    raw.columns = [c.strip().upper() for c in raw.columns]
    expected = {"TID", spec.source_dim, contract["source"]["value_column"]}
    absent = expected - set(raw.columns)
    if absent:
        raise ValueError(f"{product_id}: kolonner mangler i kildesvaret: {sorted(absent)}")

    value_text = raw[contract["source"]["value_column"]].str.strip()
    value = pd.to_numeric(
        value_text.where(value_text != missing).str.replace(",", ".", regex=False),
        errors="coerce",
    )
    batch = pd.DataFrame(
        {
            "rate_date": parse_tid(raw["TID"]),
            spec.dim: raw[spec.source_dim].str.strip(),
            spec.value: value.astype("float64"),
        }
    )
    return batch.sort_values(spec.key).reset_index(drop=True)


def merge_silver(
    existing: pd.DataFrame | None,
    batch: pd.DataFrame,
    product_id: str,
    run_id: str,
    ingested_at: str,
) -> tuple[pd.DataFrame, dict]:
    """Idempotent upsert på nøglen (rate_date, dimension).

    Svarer til MERGE INTO i Delta Lake: nye rækker indsættes, ændrede værdier
    overskrives (og tælles som revisioner), uændrede rækker røres ikke.
    """
    spec = PRODUCTS[product_id]
    incoming = batch.copy()
    incoming["run_id"] = run_id
    incoming["ingested_at"] = ingested_at

    if existing is None or existing.empty:
        merged = incoming
        stats = {"inserted": len(incoming), "revised": 0, "unchanged": 0, "filled": 0,
                 "source_missing": 0}
        return merged.sort_values(spec.key).reset_index(drop=True), stats

    current = existing.copy()
    current["rate_date"] = pd.to_datetime(current["rate_date"]).dt.date
    joined = incoming.merge(current[spec.key + [spec.value]], on=spec.key, how="left",
                            suffixes=("", "_old"), indicator=True)
    old = joined[f"{spec.value}_old"]
    new = joined[spec.value]
    is_new_key = joined["_merge"] == "left_only"
    same = np.isclose(old.fillna(0), new.fillna(0)) & (old.isna() == new.isna())
    filled = (~is_new_key) & old.isna() & new.notna()
    # En kilde, der pludselig mangler en værdi, vi allerede har, overskriver ikke.
    dropped = (~is_new_key) & old.notna() & new.isna()
    revised = (~is_new_key) & old.notna() & new.notna() & ~same

    changed_rows = joined[is_new_key | filled | revised][incoming.columns]
    keep_keys = pd.MultiIndex.from_frame(changed_rows[spec.key])
    current_idx = pd.MultiIndex.from_frame(current[spec.key])
    merged = pd.concat([current[~current_idx.isin(keep_keys)], changed_rows], ignore_index=True)

    stats = {
        "inserted": int(is_new_key.sum()),
        "revised": int(revised.sum()),
        "filled": int(filled.sum()),
        "unchanged": int(((~is_new_key) & ~filled & ~revised).sum()),
        "source_missing": int(dropped.sum()),
    }
    return merged.sort_values(spec.key).reset_index(drop=True), stats


def build_gold(silver: pd.DataFrame, product_id: str, labels: dict) -> pd.DataFrame:
    """Silver -> forbrugsklar tabel med navne og ændring siden forrige bankdag."""
    spec = PRODUCTS[product_id]
    df = silver.dropna(subset=[spec.value]).copy()
    df["rate_date"] = pd.to_datetime(df["rate_date"]).dt.date
    df = df.sort_values(spec.key).reset_index(drop=True)
    previous = df.groupby(spec.dim)[spec.value].shift(1)

    if product_id == "fx_daily":
        gold = pd.DataFrame(
            {
                "rate_date": df["rate_date"],
                "currency": df["currency"],
                "currency_name": df["currency"].map(labels).fillna(df["currency"]),
                "dkk_per_100": df["dkk_per_100"].round(4),
                "dkk_per_unit": (df["dkk_per_100"] / 100).round(6),
                "change_1d_pct": ((df["dkk_per_100"] / previous - 1) * 100).round(4),
            }
        )
    elif product_id == "policy_rates_daily":
        gold = pd.DataFrame(
            {
                "rate_date": df["rate_date"],
                "instrument": df["instrument"],
                "instrument_name": df["instrument"].map(labels).fillna(df["instrument"]),
                "rate_pct": df["rate_pct"].round(4),
                "change_bp": ((df["rate_pct"] - previous) * 100).round(2),
            }
        )
    else:  # pragma: no cover
        raise KeyError(product_id)
    gold["run_id"] = df["run_id"].values
    return gold


def to_columnar(df: pd.DataFrame) -> dict:
    """Kompakt JSON-form: kolonner én gang, derefter rækker som lister."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object and len(out) and hasattr(out[col].iloc[0], "isoformat"):
            out[col] = out[col].map(lambda d: d.isoformat())
    out = out.astype(object).where(pd.notna(out), None)
    return {"columns": list(out.columns), "rows": out.values.tolist()}
