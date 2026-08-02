-- =============================================================================
-- Aurelia Assicurazioni S.p.A. — non-life underwriting risk data mart
-- Target: DuckDB (PostgreSQL-compatible with the noted substitutions)
--   duckdb aurelia_scr.db < sql/01_schema_and_load.sql
-- =============================================================================

DROP TABLE IF EXISTS fact_lob_input;
DROP TABLE IF EXISTS fact_correlation;
DROP TABLE IF EXISTS fact_geographic_share;
DROP TABLE IF EXISTS dim_lob;

CREATE TABLE dim_lob (
    lob_code       VARCHAR(16) PRIMARY KEY,
    lob_name       VARCHAR(64)  NOT NULL,
    risk_family    VARCHAR(24)  NOT NULL,
    np_eligible    BOOLEAN      NOT NULL
);

CREATE TABLE fact_lob_input (
    lob_code        VARCHAR(16) PRIMARY KEY,
    p_last          DECIMAL(18, 2) NOT NULL,   -- premium earned, last 12 months
    p_next          DECIMAL(18, 2) NOT NULL,   -- premium expected, next 12 months
    fp_existing     DECIMAL(18, 2) NOT NULL,   -- PV of premiums, existing contracts
    fp_future       DECIMAL(18, 2) NOT NULL,   -- PV of premiums, future contracts
    pco             DECIMAL(18, 2) NOT NULL,   -- best estimate claims outstanding
    sigma_premium   DECIMAL(8, 4)  NOT NULL,
    sigma_reserve   DECIMAL(8, 4)  NOT NULL
);

CREATE TABLE fact_correlation (
    lob_code_i  VARCHAR(16) NOT NULL,
    lob_code_j  VARCHAR(16) NOT NULL,
    corr        DECIMAL(6, 4) NOT NULL,
    PRIMARY KEY (lob_code_i, lob_code_j)
);

CREATE TABLE fact_geographic_share (
    lob_code       VARCHAR(16)  NOT NULL,
    region         VARCHAR(32)  NOT NULL,
    premium_share  DECIMAL(6, 4) NOT NULL,
    reserve_share  DECIMAL(6, 4) NOT NULL,
    PRIMARY KEY (lob_code, region)
);

-- --- Load --------------------------------------------------------------------
INSERT INTO dim_lob
SELECT lob_code, lob_name,
       CASE WHEN lob_code IN ('MTPL', 'MOTOR_OTHER') THEN 'Motor'
            WHEN lob_code = 'FIRE'                   THEN 'Property'
            ELSE 'Liability' END,
       np_eligible
FROM read_csv_auto('data/lob_inputs.csv');

INSERT INTO fact_lob_input
SELECT lob_code, p_last, p_next, fp_existing, fp_future,
       pco, sigma_premium, sigma_reserve
FROM read_csv_auto('data/lob_inputs.csv');

-- The correlation matrix arrives wide; UNPIVOT normalises it to long form.
INSERT INTO fact_correlation
SELECT lob_code AS lob_code_i, lob_code_j, corr
FROM (
    SELECT * FROM read_csv_auto('data/correlation_matrix.csv')
) w
UNPIVOT (corr FOR lob_code_j IN (MTPL, MOTOR_OTHER, FIRE, GL, LEGAL));

INSERT INTO fact_geographic_share
SELECT lob_code, region, premium_share, reserve_share
FROM read_csv_auto('data/geographic_diversification.csv');

-- --- Data quality gate: every check must return 0 failures -------------------
CREATE OR REPLACE VIEW v_data_quality AS
SELECT 'correlation not symmetric' AS check_name, COUNT(*) AS failures
FROM fact_correlation a
JOIN fact_correlation b ON a.lob_code_i = b.lob_code_j
                       AND a.lob_code_j = b.lob_code_i
WHERE ABS(a.corr - b.corr) > 1e-9
UNION ALL
SELECT 'diagonal not equal to one', COUNT(*)
FROM fact_correlation WHERE lob_code_i = lob_code_j AND ABS(corr - 1) > 1e-9
UNION ALL
SELECT 'correlation outside [-1,1]', COUNT(*)
FROM fact_correlation WHERE corr < -1 OR corr > 1
UNION ALL
SELECT 'regional shares do not sum to one', COUNT(*)
FROM (SELECT lob_code, SUM(premium_share) AS s
      FROM fact_geographic_share GROUP BY lob_code) t
WHERE ABS(s - 1) > 1e-6
UNION ALL
SELECT 'negative volume input', COUNT(*)
FROM fact_lob_input
WHERE p_last < 0 OR p_next < 0 OR fp_existing < 0 OR fp_future < 0 OR pco < 0;
