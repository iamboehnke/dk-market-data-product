"""Indlæsning i Azure SQL (serving-laget) med MERGE og en kørselslog.

Bruger Microsofts mssql-python-driver, som ikke kræver en installeret ODBC-driver
og kan logge ind med funktionsappens managed identity
(Authentication=ActiveDirectoryMSI). Lokalt bruges ActiveDirectoryDefault,
så din `az login` gælder.

Gratis-tilbuddet på Azure SQL pauser databasen, når den ikke bruges. Første
forbindelse efter en pause kan tage op til et minut, derfor prøver vi igen.
"""
from __future__ import annotations

import time

import pandas as pd

GOLD_TABLES = {
    "fx_daily": {
        "table": "gold.fx_daily",
        "key": ["rate_date", "currency"],
        "columns": ["rate_date", "currency", "currency_name", "dkk_per_100", "dkk_per_unit", "change_1d_pct", "run_id"],
        "types": ["DATE", "CHAR(3)", "NVARCHAR(60)", "DECIMAL(12,4)", "DECIMAL(14,6)", "DECIMAL(9,4)", "VARCHAR(40)"],
    },
    "policy_rates_daily": {
        "table": "gold.policy_rate_daily",
        "key": ["rate_date", "instrument"],
        "columns": ["rate_date", "instrument", "instrument_name", "rate_pct", "change_bp", "run_id"],
        "types": ["DATE", "VARCHAR(10)", "NVARCHAR(60)", "DECIMAL(9,4)", "DECIMAL(9,2)", "VARCHAR(40)"],
    },
}


class SqlLoader:
    def __init__(self, server: str, database: str, authentication: str):
        self.conn_str = (
            f"Server=tcp:{server},1433;Database={database};Authentication={authentication};"
            "Encrypt=yes;TrustServerCertificate=no;"
        )
        self.conn = None

    def __enter__(self):
        import mssql_python

        last_error = None
        for attempt in range(1, 6):
            try:
                self.conn = mssql_python.connect(self.conn_str)
                return self
            except Exception as exc:  # databasen vågner fra auto-pause
                last_error = exc
                time.sleep(15 * attempt)
        raise RuntimeError(f"Kunne ikke forbinde til Azure SQL: {last_error}") from last_error

    def __exit__(self, *exc):
        if self.conn is not None:
            self.conn.close()

    def merge_gold(self, product_id: str, gold: pd.DataFrame) -> int:
        """Upsert via en midlertidig tabel og MERGE. Kan køres igen uden dubletter."""
        spec = GOLD_TABLES[product_id]
        cols, key = spec["columns"], spec["key"]
        rows = gold[cols].astype(object).where(pd.notna(gold[cols]), None).values.tolist()
        if not rows:
            return 0
        cur = self.conn.cursor()
        col_defs = ", ".join(f"{c} {t}" for c, t in zip(cols, spec["types"]))
        cur.execute(f"CREATE TABLE #stage ({col_defs});")
        placeholders = ", ".join("?" for _ in cols)
        cur.executemany(f"INSERT INTO #stage ({', '.join(cols)}) VALUES ({placeholders});", rows)
        on = " AND ".join(f"t.{k} = s.{k}" for k in key)
        update = ", ".join(f"t.{c} = s.{c}" for c in cols if c not in key)
        cur.execute(
            f"""
            MERGE {spec['table']} AS t
            USING #stage AS s ON {on}
            WHEN MATCHED THEN UPDATE SET {update}, t.loaded_at = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}, loaded_at)
                 VALUES ({', '.join('s.' + c for c in cols)}, SYSUTCDATETIME());
            """
        )
        cur.execute("DROP TABLE #stage;")
        self.conn.commit()
        return len(rows)

    def log_run(self, run: dict) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO ops.pipeline_run
                (run_id, started_at, finished_at, status, checks_total, checks_passed,
                 errors, warnings, rows_inserted, rows_revised, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                run["run_id"], run["started_at"], run["finished_at"], run["status"],
                run["quality"]["total"], run["quality"]["passed"], run["quality"]["errors"],
                run["quality"]["warnings"],
                sum(p["merge"].get("inserted", 0) for p in run["products"].values()),
                sum(p["merge"].get("revised", 0) for p in run["products"].values()),
                run["details_json"],
            ),
        )
        self.conn.commit()
