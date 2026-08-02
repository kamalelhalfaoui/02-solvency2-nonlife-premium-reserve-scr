"""
Non-life premium and reserve risk under the Solvency II standard formula.

Implements the volume measures, per-segment volatility, correlation aggregation
and capital charge described in Articles 115-117 of the Delegated Regulation,
plus three refinements that the textbook version of the exercise leaves out:

  * the geographical diversification factor applied to the volume measure;
  * the non-proportional reinsurance adjustment to premium volatility;
  * an Euler allocation of the diversified capital charge back to segment.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# The standard formula expresses the 99.5% charge as three standard deviations
# under a lognormal assumption; the multiplier is fixed by the Regulation.
SCR_MULTIPLIER = 3.0

# Correlation between premium and reserve risk within a segment (Annex III)
PREMIUM_RESERVE_CORRELATION = 0.5

# Adjustment applied to premium volatility where adequate excess-of-loss cover
# is in place, available only to certain segments (Article 117(3))
NP_ADJUSTMENT_FACTOR = 0.80


@dataclass
class PremiumReserveRisk:
    """Premium and reserve risk sub-module.

    Parameters
    ----------
    inputs : pd.DataFrame
        One row per segment with columns ``lob_code``, ``lob_name``, ``p_last``,
        ``p_next``, ``fp_existing``, ``fp_future``, ``pco``, ``sigma_premium``,
        ``sigma_reserve``, ``np_eligible``.
    correlation : pd.DataFrame
        Square segment correlation matrix indexed and columned by ``lob_code``.
    diversification : pd.Series or None
        Geographical diversification factor ``DIV`` per segment. ``None`` means
        no geographical diversification is recognised (equivalent to DIV = 1).
    apply_np_adjustment : bool
        Whether to apply the non-proportional reinsurance factor to eligible
        segments.
    """

    inputs: pd.DataFrame
    correlation: pd.DataFrame
    diversification: pd.Series | None = None
    apply_np_adjustment: bool = False

    segments: pd.DataFrame = field(init=False)

    def __post_init__(self) -> None:
        self.inputs = self.inputs.set_index("lob_code", drop=False)
        self.correlation = self.correlation.loc[self.inputs.index,
                                                self.inputs.index]
        self.segments = self._build_segments()

    # ------------------------------------------------------------- volumes
    def _build_segments(self) -> pd.DataFrame:
        df = self.inputs.copy()

        # Article 116(3): premium volume is the larger of the premium earned in
        # the last year and that expected in the next, plus the present value of
        # premiums on existing and future contracts.
        df["v_premium_gross"] = (df[["p_last", "p_next"]].max(axis=1)
                                 + df["fp_existing"] + df["fp_future"])
        df["v_reserve"] = df["pco"]

        # Article 116(7): geographical diversification is recognised through a
        # factor that can reduce the volume measure by at most 25%.
        if self.diversification is None:
            df["div_factor"] = 1.0
        else:
            df["div_factor"] = self.diversification.reindex(df.index).fillna(1.0)
        df["volume_scalar"] = 0.75 + 0.25 * df["div_factor"]

        df["v_premium"] = df["v_premium_gross"] * df["volume_scalar"]
        df["v_reserve"] = df["v_reserve"] * df["volume_scalar"]
        df["v_total"] = df["v_premium"] + df["v_reserve"]

        # Article 117(3): the non-proportional adjustment applies to premium
        # volatility only, and only for eligible segments.
        eligible = df["np_eligible"].astype(bool) & self.apply_np_adjustment
        df["np_factor"] = np.where(eligible, NP_ADJUSTMENT_FACTOR, 1.0)
        df["sigma_premium_adj"] = df["sigma_premium"] * df["np_factor"]

        # Combined segment volatility: premium and reserve risk aggregated at a
        # correlation of 0.5, which produces the cross term below.
        prem = df["sigma_premium_adj"] * df["v_premium"]
        res = df["sigma_reserve"] * df["v_reserve"]
        numerator = np.sqrt(prem ** 2
                            + 2 * PREMIUM_RESERVE_CORRELATION * prem * res
                            + res ** 2)
        df["sigma_lob"] = numerator / df["v_total"]
        df["sigma_v"] = df["sigma_lob"] * df["v_total"]

        # Standalone charges, i.e. before any cross-segment diversification
        df["scr_premium_standalone"] = SCR_MULTIPLIER * prem
        df["scr_reserve_standalone"] = SCR_MULTIPLIER * res
        df["scr_lob_standalone"] = SCR_MULTIPLIER * df["sigma_v"]
        return df

    # ----------------------------------------------------------- aggregation
    @property
    def sigma_vector(self) -> np.ndarray:
        return self.segments["sigma_v"].to_numpy()

    @property
    def total_volume(self) -> float:
        return float(self.segments["v_total"].sum())

    @property
    def aggregate_sigma_volume(self) -> float:
        """sqrt(x' C x) where x_s = sigma_s * V_s."""
        x = self.sigma_vector
        return float(np.sqrt(x @ self.correlation.to_numpy() @ x))

    @property
    def sigma_company(self) -> float:
        return self.aggregate_sigma_volume / self.total_volume

    @property
    def scr(self) -> float:
        return SCR_MULTIPLIER * self.aggregate_sigma_volume

    @property
    def scr_undiversified(self) -> float:
        """Simple sum of the standalone segment charges."""
        return float(self.segments["scr_lob_standalone"].sum())

    @property
    def diversification_benefit(self) -> float:
        return self.scr_undiversified - self.scr

    @property
    def diversification_benefit_pct(self) -> float:
        return self.diversification_benefit / self.scr_undiversified

    # ------------------------------------------------------------ allocation
    def euler_allocation(self) -> pd.DataFrame:
        """Allocate the diversified charge to segment by Euler contribution.

        The charge is homogeneous of degree one in x, so the marginal
        contributions x_s * dSCR/dx_s sum exactly to the total. This is the
        allocation that reflects each segment's contribution *given* the rest of
        the portfolio, rather than its standalone size.
        """
        x = self.sigma_vector
        corr = self.correlation.to_numpy()
        aggregate = self.aggregate_sigma_volume
        marginal = SCR_MULTIPLIER * (corr @ x) / aggregate
        contribution = x * marginal

        out = pd.DataFrame({
            "lob_code": self.segments["lob_code"],
            "lob_name": self.segments["lob_name"],
            "scr_standalone": self.segments["scr_lob_standalone"],
            "scr_allocated": contribution,
        })
        out["diversification_credit"] = (out["scr_standalone"]
                                         - out["scr_allocated"])
        out["credit_pct"] = out["diversification_credit"] / out["scr_standalone"]
        out["share_of_total"] = out["scr_allocated"] / out["scr_allocated"].sum()
        return out.reset_index(drop=True)

    # --------------------------------------------------------------- reports
    def volume_table(self) -> pd.DataFrame:
        cols = ["lob_code", "lob_name", "v_premium", "v_reserve", "v_total",
                "sigma_premium_adj", "sigma_reserve", "sigma_lob",
                "scr_lob_standalone"]
        return self.segments[cols].reset_index(drop=True)

    def summary(self) -> dict:
        return {
            "total_volume": self.total_volume,
            "sigma_company": self.sigma_company,
            "scr_diversified": self.scr,
            "scr_undiversified": self.scr_undiversified,
            "diversification_benefit": self.diversification_benefit,
            "diversification_benefit_pct": self.diversification_benefit_pct,
        }

    # ---------------------------------------------------------- sensitivity
    def with_shocked_volume(self, lob_code: str, factor: float
                            ) -> "PremiumReserveRisk":
        """Return a copy with one segment's premium volume scaled."""
        shocked = self.inputs.copy()
        columns = ["p_last", "p_next", "fp_existing", "fp_future"]
        shocked[columns] = shocked[columns].astype(float)
        shocked.loc[lob_code, columns] *= factor
        return PremiumReserveRisk(shocked.reset_index(drop=True),
                                  self.correlation.copy(),
                                  self.diversification,
                                  self.apply_np_adjustment)


def herfindahl_index(shares: np.ndarray) -> float:
    """Concentration of the portfolio across segments; 1 = single segment."""
    return float((shares ** 2).sum())


def geographic_diversification_factor(shares: pd.DataFrame) -> pd.Series:
    """Compute DIV per segment from regional premium and reserve shares.

    Article 116(7) defines DIV as the sum of squared regional shares of the
    combined premium and reserve volume for the segment. A segment written
    entirely in one region has DIV = 1 and receives no credit; a segment spread
    evenly over four regions has DIV = 0.25, the minimum attainable, and
    receives the maximum reduction in the volume measure.
    """
    combined = shares.assign(
        share=(shares["premium_share"] + shares["reserve_share"]) / 2.0)
    return (combined.assign(share_squared=lambda d: d["share"] ** 2)
                    .groupby("lob_code")["share_squared"]
                    .sum()
                    .rename("div_factor"))
