-- Eksempler til samtalen: vis, at serving-laget kan bruges direkte

-- Seneste kurser og renter
SELECT * FROM gold.v_latest ORDER BY kind, code;

-- Hvornår ændrede Nationalbanken renten, og hvor meget?
SELECT rate_date, instrument_name, rate_pct, change_bp
FROM gold.policy_rate_daily
WHERE change_bp <> 0 AND instrument = 'OFONAA'
ORDER BY rate_date DESC;

-- Euroens afstand til centralkursen 746,038 (fastkurspolitikken i praksis)
SELECT rate_date, dkk_per_100,
       CAST((dkk_per_100 / 746.038 - 1) * 100 AS DECIMAL(6,3)) AS afvigelse_pct
FROM gold.fx_daily
WHERE currency = 'EUR'
ORDER BY rate_date DESC;

-- Lineage: hvilken kørsel skrev de seneste rækker, og hvordan gik den?
SELECT TOP 10 r.run_id, r.status, r.checks_passed, r.checks_total, r.rows_inserted, r.rows_revised
FROM ops.pipeline_run r
ORDER BY r.started_at DESC;
