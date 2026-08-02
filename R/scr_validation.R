###############################################################################
# Aurelia Assicurazioni S.p.A. - premium and reserve risk, independent rebuild
#
# The Python engine computes sqrt(x' C x) directly. This script rebuilds the
# module in base R using matrix algebra, then cross-checks the correlation
# aggregation by Monte Carlo: if the closed form is right, the standard
# deviation of a simulated correlated portfolio loss must reproduce it.
#
# Base R only. Run from the repository root:
#   Rscript R/scr_validation.R
###############################################################################

set.seed(20250802)

SCR_MULTIPLIER  <- 3.0
PREM_RES_CORR   <- 0.5
N_SIMULATIONS   <- 200000
TOLERANCE       <- 1e-8

# ---------------------------------------------------------------------------
# 1. Load
# ---------------------------------------------------------------------------
inputs <- read.csv("data/lob_inputs.csv", stringsAsFactors = FALSE)
corr_raw <- read.csv("data/correlation_matrix.csv", stringsAsFactors = FALSE)

lob <- inputs$lob_code
n   <- length(lob)

corr <- as.matrix(corr_raw[, lob])
rownames(corr) <- corr_raw$lob_code
corr <- corr[lob, lob]

# ---------------------------------------------------------------------------
# 2. Matrix properties - a correlation matrix that is not positive
#    semi-definite would make sqrt(x' C x) meaningless for some x.
# ---------------------------------------------------------------------------
cat("=====================================================================\n")
cat("1. CORRELATION MATRIX PROPERTIES\n")
cat("=====================================================================\n")

eigenvalues <- eigen(corr, symmetric = TRUE)$values
cat(sprintf("Symmetric                : %s\n", isTRUE(all.equal(corr, t(corr)))))
cat(sprintf("Unit diagonal            : %s\n", all(abs(diag(corr) - 1) < 1e-12)))
cat(sprintf("Eigenvalues              : %s\n",
            paste(round(eigenvalues, 4), collapse = ", ")))
cat(sprintf("Positive semi-definite   : %s\n", all(eigenvalues > -1e-9)))
cat(sprintf("Condition number         : %.2f\n",
            max(eigenvalues) / min(eigenvalues)))

if (any(eigenvalues < -1e-9)) {
  cat("\nFAIL - matrix is not positive semi-definite.\n")
  quit(status = 1)
}

# ---------------------------------------------------------------------------
# 3. Volume measures and segment volatility
# ---------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("2. VOLUME MEASURES AND SEGMENT VOLATILITY\n")
cat("=====================================================================\n")

v_premium <- pmax(inputs$p_last, inputs$p_next) +
             inputs$fp_existing + inputs$fp_future
v_reserve <- inputs$pco
v_total   <- v_premium + v_reserve

x_prem <- inputs$sigma_premium * v_premium
x_res  <- inputs$sigma_reserve * v_reserve

# Premium and reserve risk combine at a correlation of 0.5 within the segment
sigma_v   <- sqrt(x_prem^2 + 2 * PREM_RES_CORR * x_prem * x_res + x_res^2)
sigma_lob <- sigma_v / v_total

segments <- data.frame(
  lob            = lob,
  v_premium_m    = round(v_premium / 1e6, 1),
  v_reserve_m    = round(v_reserve / 1e6, 1),
  v_total_m      = round(v_total   / 1e6, 1),
  sigma_lob      = round(sigma_lob, 6),
  scr_standalone = round(SCR_MULTIPLIER * sigma_v / 1e6, 2)
)
print(segments, row.names = FALSE)

# ---------------------------------------------------------------------------
# 4. Aggregation
# ---------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("3. AGGREGATION\n")
cat("=====================================================================\n")

x <- sigma_v
aggregate_sigma_volume <- sqrt(as.numeric(t(x) %*% corr %*% x))

total_volume      <- sum(v_total)
sigma_company     <- aggregate_sigma_volume / total_volume
scr_diversified   <- SCR_MULTIPLIER * aggregate_sigma_volume
scr_undiversified <- sum(SCR_MULTIPLIER * sigma_v)
benefit           <- scr_undiversified - scr_diversified

cat(sprintf("Total volume V           : EUR %.2f m\n", total_volume / 1e6))
cat(sprintf("Company sigma            : %.4f%%\n",     sigma_company * 100))
cat(sprintf("Sum of standalone SCR    : EUR %.2f m\n", scr_undiversified / 1e6))
cat(sprintf("Diversified SCR          : EUR %.2f m\n", scr_diversified / 1e6))
cat(sprintf("Diversification benefit  : EUR %.2f m (%.1f%%)\n",
            benefit / 1e6, 100 * benefit / scr_undiversified))

# ---------------------------------------------------------------------------
# 5. Monte Carlo cross-check of the closed-form aggregation
#
#    Draw correlated standard normals with covariance C via Cholesky, scale each
#    margin by x_s, and sum. The resulting portfolio total has standard deviation
#    sqrt(x' C x) by construction, so agreement confirms the quadratic form has
#    been assembled correctly - in particular that no off-diagonal pair has been
#    double-counted or dropped.
# ---------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("4. MONTE CARLO CROSS-CHECK OF THE QUADRATIC FORM\n")
cat("=====================================================================\n")

chol_factor <- chol(corr)                       # upper triangular, t(R) %*% R = C
z <- matrix(rnorm(N_SIMULATIONS * n), nrow = N_SIMULATIONS, ncol = n)
correlated <- z %*% chol_factor                 # rows are correlated draws

portfolio <- as.numeric(correlated %*% x)
simulated_sd <- sd(portfolio)

relative_error <- abs(simulated_sd - aggregate_sigma_volume) / aggregate_sigma_volume

cat(sprintf("Closed form sqrt(x'Cx)   : EUR %.4f m\n", aggregate_sigma_volume / 1e6))
cat(sprintf("Simulated (%s draws) : EUR %.4f m\n",
            format(N_SIMULATIONS, big.mark = ","), simulated_sd / 1e6))
cat(sprintf("Relative error           : %.4f%%\n", relative_error * 100))

# Monte Carlo error on a standard deviation is of order 1/sqrt(2N)
mc_tolerance <- 5 / sqrt(2 * N_SIMULATIONS)
if (relative_error < mc_tolerance) {
  cat(sprintf("\nPASS - within Monte Carlo error (%.4f%%).\n", mc_tolerance * 100))
} else {
  cat("\nFAIL - the quadratic form does not reproduce the simulated portfolio.\n")
  quit(status = 1)
}

# ---------------------------------------------------------------------------
# 6. Euler allocation, verified to sum to the total
# ---------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("5. EULER ALLOCATION\n")
cat("=====================================================================\n")

marginal     <- SCR_MULTIPLIER * as.numeric(corr %*% x) / aggregate_sigma_volume
contribution <- x * marginal

allocation <- data.frame(
  lob            = lob,
  standalone_m   = round(SCR_MULTIPLIER * sigma_v / 1e6, 2),
  allocated_m    = round(contribution / 1e6, 2),
  credit_pct     = round(100 * (1 - contribution / (SCR_MULTIPLIER * sigma_v)), 1),
  share_pct      = round(100 * contribution / sum(contribution), 1)
)
print(allocation, row.names = FALSE)

reconciliation <- abs(sum(contribution) - scr_diversified) / scr_diversified
cat(sprintf("\nAllocation sums to EUR %.2f m against SCR of EUR %.2f m\n",
            sum(contribution) / 1e6, scr_diversified / 1e6))
cat(sprintf("Relative reconciliation gap: %.2e\n", reconciliation))

if (reconciliation < TOLERANCE) {
  cat("PASS - Euler additivity holds.\n")
} else {
  cat("FAIL - allocation does not reconcile.\n")
  quit(status = 1)
}

# ---------------------------------------------------------------------------
# 7. Marginal capital: what one extra euro of volume costs in each segment
# ---------------------------------------------------------------------------
cat("\n=====================================================================\n")
cat("6. MARGINAL CAPITAL INTENSITY\n")
cat("=====================================================================\n")

intensity <- data.frame(
  lob                  = lob,
  standalone_intensity = round(SCR_MULTIPLIER * sigma_lob, 4),
  diversified_intensity = round(contribution / v_total, 4),
  ratio                = round((contribution / v_total) /
                               (SCR_MULTIPLIER * sigma_lob), 3)
)
print(intensity, row.names = FALSE)

cat("\nCapital per euro of volume, standalone and after diversification. The\n")
cat("ratio is the share of standalone capital cost that survives aggregation -\n")
cat("the lower it is, the more the segment is subsidised by the rest of the book.\n")

dir.create("outputs/tables", showWarnings = FALSE, recursive = TRUE)
write.csv(allocation, "outputs/tables/r_euler_allocation.csv", row.names = FALSE)
write.csv(intensity,  "outputs/tables/r_capital_intensity.csv", row.names = FALSE)

cat("\nValidation complete.\n")
