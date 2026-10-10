-- Kør én gang i databasen (Query editor i portalen eller Azure Data Studio),
-- logget ind som Entra-administrator på SQL-serveren.

IF SCHEMA_ID('gold') IS NULL EXEC('CREATE SCHEMA gold');
IF SCHEMA_ID('ops')  IS NULL EXEC('CREATE SCHEMA ops');
GO

IF OBJECT_ID('gold.fx_daily') IS NULL
CREATE TABLE gold.fx_daily (
    rate_date      DATE           NOT NULL,
    currency       CHAR(3)        NOT NULL,
    currency_name  NVARCHAR(60)   NOT NULL,
    dkk_per_100    DECIMAL(12,4)  NOT NULL,
    dkk_per_unit   DECIMAL(14,6)  NOT NULL,
    change_1d_pct  DECIMAL(9,4)   NULL,
    run_id         VARCHAR(40)    NOT NULL,   -- lineage: hvilken kørsel skrev rækken
    loaded_at      DATETIME2(0)   NOT NULL,
    CONSTRAINT pk_fx_daily PRIMARY KEY (rate_date, currency)
);
GO

IF OBJECT_ID('gold.policy_rate_daily') IS NULL
CREATE TABLE gold.policy_rate_daily (
    rate_date        DATE          NOT NULL,
    instrument       VARCHAR(10)   NOT NULL,
    instrument_name  NVARCHAR(60)  NOT NULL,
    rate_pct         DECIMAL(9,4)  NOT NULL,
    change_bp        DECIMAL(9,2)  NULL,
    run_id           VARCHAR(40)   NOT NULL,
    loaded_at        DATETIME2(0)  NOT NULL,
    CONSTRAINT pk_policy_rate_daily PRIMARY KEY (rate_date, instrument)
);
GO

IF OBJECT_ID('ops.pipeline_run') IS NULL
CREATE TABLE ops.pipeline_run (
    run_id         VARCHAR(40)     NOT NULL PRIMARY KEY,
    started_at     DATETIMEOFFSET(0) NOT NULL,
    finished_at    DATETIMEOFFSET(0) NOT NULL,
    status         VARCHAR(20)     NOT NULL,
    checks_total   INT             NOT NULL,
    checks_passed  INT             NOT NULL,
    errors         INT             NOT NULL,
    warnings       INT             NOT NULL,
    rows_inserted  INT             NOT NULL,
    rows_revised   INT             NOT NULL,
    details_json   NVARCHAR(4000)  NULL
);
GO

-- En visning, som en analytiker eller et BI-værktøj kan bruge direkte
CREATE OR ALTER VIEW gold.v_latest AS
SELECT 'fx' AS kind, currency AS code, currency_name AS name, rate_date, dkk_per_unit AS value
FROM gold.fx_daily WHERE rate_date = (SELECT MAX(rate_date) FROM gold.fx_daily)
UNION ALL
SELECT 'rate', instrument, instrument_name, rate_date, rate_pct
FROM gold.policy_rate_daily p
WHERE rate_date = (SELECT MAX(rate_date) FROM gold.policy_rate_daily x WHERE x.instrument = p.instrument);
GO
