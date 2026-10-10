"""Kvalitetstjek drevet af datakontrakten (YAML).

Hvert tjek giver et resultat med alvorlighed. Fejler et tjek med severity
"error", publiceres batchen ikke: silver og gold bliver ved den seneste gode
version, og batchen lægges i karantæne. "warn" logges, men blokerer ikke.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def _result(check: dict, passed: bool, details: str, severity: str | None = None,
            failing: int = 0) -> dict:
    return {
        "check": check["check"],
        "target": check.get("column") or ",".join(check.get("columns", [])),
        "description": check.get("description", ""),
        "severity": severity or check.get("severity", "error"),
        "passed": bool(passed),
        "failing_rows": int(failing),
        "details": details,
    }


def _apply_where(df: pd.DataFrame, where: dict | None) -> pd.DataFrame:
    if not where:
        return df
    mask = pd.Series(True, index=df.index)
    for col, value in where.items():
        mask &= df[col] == value
    return df[mask]


def _check_not_null(df, check):
    nulls = df[check["columns"]].isna().any(axis=1)
    sample = df[nulls].head(3).astype(str).to_dict("records")
    return _result(check, not nulls.any(), f"{int(nulls.sum())} rækker med tomme værdier"
                   + (f", fx {sample}" if sample else ""), failing=nulls.sum())


def _check_unique(df, check):
    dupes = df.duplicated(subset=check["columns"], keep=False)
    return _result(check, not dupes.any(), f"{int(dupes.sum())} dublerede rækker", failing=dupes.sum())


def _check_accepted_values(df, check):
    bad = ~df[check["column"]].isin(check["values"])
    found = sorted(df.loc[bad, check["column"]].astype(str).unique())[:5]
    return _result(check, not bad.any(), f"Ukendte værdier: {found}" if found else "Alle værdier kendte",
                   failing=bad.sum())


def _check_range(df, check):
    scoped = _apply_where(df, check.get("where"))
    values = scoped[check["column"]].dropna()
    bad = pd.Series(False, index=values.index)
    if "min" in check:
        bad |= values < check["min"]
    if "max" in check:
        bad |= values > check["max"]
    span = f"[{check.get('min', '-inf')}; {check.get('max', 'inf')}]"
    if bad.any():
        details = f"{int(bad.sum())} værdier uden for {span}, fx {values[bad].head(3).tolist()}"
    else:
        details = f"Alle {len(values)} værdier inden for {span}"
    return _result(check, not bad.any(), details, failing=bad.sum())


def _check_max_abs_change(df, check, scale: float, unit: str):
    col, group = check["column"], check["group_by"]
    ordered = df.dropna(subset=[col]).sort_values(["rate_date", group])
    change = ordered.groupby(group)[col].diff()
    if unit == "%":
        change = change / ordered.groupby(group)[col].shift(1) * 100
    else:
        change = change * scale
    bad = change.abs() > check["max"]
    worst = ordered.loc[bad, [group, "rate_date"]].assign(change=change[bad].round(2)).head(3)
    details = (f"{int(bad.sum())} udsving over {check['max']} {unit}: {worst.astype(str).to_dict('records')}"
               if bad.any() else f"Ingen udsving over {check['max']} {unit}")
    return _result(check, not bad.any(), details, failing=bad.sum())


def _check_complete_per_date(df, check):
    recent_dates = sorted(df["rate_date"].unique())[-check.get("last_days", 10):]
    recent = df[df["rate_date"].isin(recent_dates)].dropna()
    expected = set(check["expected"])
    gaps = []
    for day, group in recent.groupby("rate_date"):
        missing = expected - set(group[check["column"]])
        if missing:
            gaps.append(f"{day}: {sorted(missing)}")
    return _result(check, not gaps, "; ".join(gaps[:3]) if gaps else
                   f"Alle forventede værdier til stede de seneste {len(recent_dates)} bankdage",
                   failing=len(gaps))


def _check_freshness(df, check, today: date):
    latest = pd.to_datetime(df[check["column"]]).max().date()
    age = (today - latest).days
    if age > check["error_after_days"]:
        severity, passed = "error", False
    elif age > check["warn_after_days"]:
        severity, passed = "warn", False
    else:
        severity, passed = "warn", True
    return _result(check, passed, f"Seneste dato {latest.isoformat()} er {age} dage gammel",
                   severity=severity)


def run_checks(batch: pd.DataFrame, merged: pd.DataFrame, checks: list[dict], today: date) -> list[dict]:
    """Rækkeniveau-tjek kører på dagens batch; friskhed og fuldstændighed på hele tabellen."""
    results = []
    for check in checks:
        kind = check["check"]
        if kind == "not_null":
            results.append(_check_not_null(batch, check))
        elif kind == "unique":
            results.append(_check_unique(batch, check))
        elif kind == "accepted_values":
            results.append(_check_accepted_values(batch, check))
        elif kind == "range":
            results.append(_check_range(batch, check))
        elif kind == "max_abs_change_pct":
            results.append(_check_max_abs_change(merged, check, 1.0, "%"))
        elif kind == "max_abs_change_bp":
            results.append(_check_max_abs_change(merged, check, 100.0, "bp"))
        elif kind == "complete_per_date":
            results.append(_check_complete_per_date(merged, check))
        elif kind == "freshness":
            results.append(_check_freshness(merged, check, today))
        else:
            raise ValueError(f"Ukendt tjek i kontrakten: {kind}")
    return results


def summarize(results: list[dict]) -> dict:
    errors = [r for r in results if not r["passed"] and r["severity"] == "error"]
    warnings = [r for r in results if not r["passed"] and r["severity"] == "warn"]
    return {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "errors": len(errors),
        "warnings": len(warnings),
        "blocking": bool(errors),
    }
