-- =============================================================================
-- Premium and reserve risk SCR computed in SQL
-- -----------------------------------------------------------------------------
-- The correlation aggregation sqrt(x' C x) becomes a self-join over the long-form
-- matrix: every ordered pair (i, j) contributes corr * x_i * x_j to one SUM.
-- =============================================================================

-- 1. Volume measures ----------------------------------------------------------
CREATE OR REPLACE VIEW v_volume_measure AS
SELECT i.lob_code,
       d.lob_name,
       d.risk_family,
       -- Cast to DOUBLE: these volumes are squared in the volatility formula
       -- and DECIMAL(18,2) overflows the moment two of them are multiplied.
       CAST(GREATEST(i.p_last, i.p_next) + i.fp_existing + i.fp_future
            AS DOUBLE)                                            AS v_premium,
       CAST(i.pco AS DOUBLE)                                      AS v_reserve,
       CAST(GREATEST(i.p_last, i.p_next) + i.fp_existing + i.fp_future
            + i.pco AS DOUBLE)                                    AS v_total,
       CAST(i.sigma_premium AS DOUBLE)                            AS sigma_premium,
       CAST(i.sigma_reserve AS DOUBLE)                            AS sigma_reserve
FROM fact_lob_input i
JOIN dim_lob        d ON d.lob_code = i.lob_code;

-- 2. Segment volatility -------------------------------------------------------
--    sigma_s = sqrt(P^2 + 2*0.5*P*R + R^2) / (V_prem + V_res)
--    where P = sigma_prem * V_prem and R = sigma_res * V_res.
CREATE OR REPLACE VIEW v_segment_sigma AS
SELECT lob_code,
       lob_name,
       risk_family,
       v_premium,
       v_reserve,
       v_total,
       sigma_premium * v_premium AS x_premium,
       sigma_reserve * v_reserve AS x_reserve,
       SQRT( POWER(sigma_premium * v_premium, 2)
           + 2 * 0.5 * (sigma_premium * v_premium) * (sigma_reserve * v_reserve)
           + POWER(sigma_reserve * v_reserve, 2) ) / v_total AS sigma_lob,
       SQRT( POWER(sigma_premium * v_premium, 2)
           + 2 * 0.5 * (sigma_premium * v_premium) * (sigma_reserve * v_reserve)
           + POWER(sigma_reserve * v_reserve, 2) )           AS sigma_v,
       3.0 * SQRT( POWER(sigma_premium * v_premium, 2)
           + 2 * 0.5 * (sigma_premium * v_premium) * (sigma_reserve * v_reserve)
           + POWER(sigma_reserve * v_reserve, 2) )           AS scr_standalone
FROM v_volume_measure;

-- 3. Correlation aggregation --------------------------------------------------
CREATE OR REPLACE VIEW v_aggregate AS
WITH quadratic AS (
    SELECT SUM(CAST(c.corr AS DOUBLE) * si.sigma_v * sj.sigma_v) AS x_c_x
    FROM fact_correlation c
    JOIN v_segment_sigma si ON si.lob_code = c.lob_code_i
    JOIN v_segment_sigma sj ON sj.lob_code = c.lob_code_j
),
totals AS (
    SELECT SUM(v_total) AS v, SUM(scr_standalone) AS scr_undiversified
    FROM v_segment_sigma
)
SELECT t.v                              AS total_volume,
       SQRT(q.x_c_x)                    AS aggregate_sigma_volume,
       SQRT(q.x_c_x) / t.v              AS sigma_company,
       3.0 * SQRT(q.x_c_x)              AS scr_diversified,
       t.scr_undiversified,
       t.scr_undiversified - 3.0 * SQRT(q.x_c_x)                       AS diversification_benefit,
       (t.scr_undiversified - 3.0 * SQRT(q.x_c_x)) / t.scr_undiversified AS diversification_benefit_pct
FROM quadratic q CROSS JOIN totals t;

-- 4. Euler allocation ---------------------------------------------------------
--    contribution_s = 3 * x_s * (C x)_s / sqrt(x' C x); these sum to the SCR.
CREATE OR REPLACE VIEW v_capital_allocation AS
WITH cx AS (
    SELECT c.lob_code_i AS lob_code,
           SUM(CAST(c.corr AS DOUBLE) * sj.sigma_v) AS c_x
    FROM fact_correlation c
    JOIN v_segment_sigma sj ON sj.lob_code = c.lob_code_j
    GROUP BY c.lob_code_i
)
SELECT s.lob_code,
       s.lob_name,
       s.scr_standalone,
       3.0 * s.sigma_v * cx.c_x / a.aggregate_sigma_volume        AS scr_allocated,
       s.scr_standalone
         - 3.0 * s.sigma_v * cx.c_x / a.aggregate_sigma_volume    AS diversification_credit,
       1 - (3.0 * s.sigma_v * cx.c_x / a.aggregate_sigma_volume)
           / s.scr_standalone                                     AS credit_pct,
       3.0 * s.sigma_v * cx.c_x / a.aggregate_sigma_volume
           / a.scr_diversified                                    AS share_of_total
FROM v_segment_sigma s
JOIN cx           ON cx.lob_code = s.lob_code
CROSS JOIN v_aggregate a
ORDER BY scr_allocated DESC;

-- 5. Geographical diversification factor --------------------------------------
--    DIV_s = sum over regions of the squared share of combined volume.
CREATE OR REPLACE VIEW v_geographic_div AS
SELECT lob_code,
       SUM( POWER(CAST(premium_share + reserve_share AS DOUBLE) / 2.0, 2) ) AS div_factor,
       0.75 + 0.25 * SUM( POWER(CAST(premium_share + reserve_share AS DOUBLE) / 2.0, 2) )
                                                              AS volume_scalar,
       COUNT(*)                                               AS n_regions
FROM fact_geographic_share
GROUP BY lob_code
ORDER BY div_factor;
