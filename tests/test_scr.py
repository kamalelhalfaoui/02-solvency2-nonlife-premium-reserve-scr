"""Unit tests for the premium and reserve risk module.  Run:  pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scr import (PremiumReserveRisk, geographic_diversification_factor,  # noqa: E402
                 herfindahl_index)


@pytest.fixture(scope="module")
def data():
    return (pd.read_csv(ROOT / "data" / "lob_inputs.csv"),
            pd.read_csv(ROOT / "data" / "correlation_matrix.csv", index_col=0))


@pytest.fixture(scope="module")
def model(data):
    inputs, corr = data
    return PremiumReserveRisk(inputs.copy(), corr.copy())


# ------------------------------------------------------------ volume measures
def test_premium_volume_takes_the_larger_of_last_and_next(model):
    row = model.segments.loc["MTPL"]
    expected = max(row["p_last"], row["p_next"]) + row["fp_existing"] + row["fp_future"]
    assert row["v_premium"] == pytest.approx(expected)


def test_reserve_volume_is_the_claims_provision(model):
    assert model.segments["v_reserve"].equals(model.segments["pco"].astype(float))


def test_total_volume_is_the_sum_of_segment_volumes(model):
    assert model.total_volume == pytest.approx(model.segments["v_total"].sum())


# --------------------------------------------------------- segment volatility
def test_segment_sigma_is_subadditive(model):
    """Premium and reserve risk aggregate at a correlation of 0.5, so the
    combined charge must sit strictly below the sum of the two components.

    Note the lower bound is NOT min(sigma_prem, sigma_res): when the two sigmas
    are equal the within-segment diversification still pulls sigma_lob below
    both of them, because sqrt(P^2 + PR + R^2) < P + R.
    """
    for code, row in model.segments.iterrows():
        combined = row["sigma_lob"] * row["v_total"]
        standalone_sum = (row["sigma_premium_adj"] * row["v_premium"]
                          + row["sigma_reserve"] * row["v_reserve"])
        assert 0 < combined < standalone_sum, code
        assert row["sigma_lob"] <= max(row["sigma_premium_adj"],
                                       row["sigma_reserve"]) + 1e-12, code


def test_equal_sigmas_still_diversify_within_the_segment():
    """sigma_lob drops below the common sigma even when premium and reserve
    volatilities are identical - the 0.5 correlation is doing the work."""
    inputs = pd.DataFrame([{
        "lob_code": "X", "lob_name": "Test", "p_last": 100.0, "p_next": 100.0,
        "fp_existing": 0.0, "fp_future": 0.0, "pco": 100.0,
        "sigma_premium": 0.10, "sigma_reserve": 0.10, "np_eligible": False}])
    corr = pd.DataFrame([[1.0]], index=["X"], columns=["X"])
    model = PremiumReserveRisk(inputs, corr)
    # sqrt(3)/2 * 0.10 = 0.0866
    assert model.segments.loc["X", "sigma_lob"] == pytest.approx(
        0.10 * np.sqrt(3) / 2)
    assert model.segments.loc["X", "sigma_lob"] < 0.10


def test_single_segment_sigma_matches_the_closed_form():
    """A one-segment portfolio has no cross-segment diversification, so the
    company sigma must equal that segment's own sigma."""
    inputs = pd.DataFrame([{
        "lob_code": "X", "lob_name": "Test", "p_last": 100.0, "p_next": 120.0,
        "fp_existing": 10.0, "fp_future": 5.0, "pco": 200.0,
        "sigma_premium": 0.10, "sigma_reserve": 0.20, "np_eligible": False}])
    corr = pd.DataFrame([[1.0]], index=["X"], columns=["X"])
    model = PremiumReserveRisk(inputs, corr)

    v_prem, v_res = 135.0, 200.0
    prem, res = 0.10 * v_prem, 0.20 * v_res
    expected = np.sqrt(prem ** 2 + prem * res + res ** 2) / (v_prem + v_res)

    assert model.segments.loc["X", "sigma_lob"] == pytest.approx(expected)
    assert model.sigma_company == pytest.approx(expected)
    assert model.scr == pytest.approx(3 * expected * 335.0)


# ------------------------------------------------------------- aggregation
def test_diversified_charge_is_below_the_sum_of_standalones(model):
    assert model.scr < model.scr_undiversified
    assert 0 < model.diversification_benefit_pct < 1


def test_perfect_correlation_removes_all_diversification(data):
    """With every correlation set to 1, sqrt(x'Cx) collapses to sum(x)."""
    inputs, corr = data
    ones = pd.DataFrame(np.ones_like(corr.to_numpy()),
                        index=corr.index, columns=corr.columns)
    model = PremiumReserveRisk(inputs.copy(), ones)
    assert model.scr == pytest.approx(model.scr_undiversified, rel=1e-10)
    assert model.diversification_benefit == pytest.approx(0.0, abs=1e-4)


def test_independence_gives_the_root_sum_of_squares(data):
    inputs, corr = data
    identity = pd.DataFrame(np.eye(len(corr)), index=corr.index,
                            columns=corr.columns)
    model = PremiumReserveRisk(inputs.copy(), identity)
    standalone = model.segments["scr_lob_standalone"].to_numpy()
    assert model.scr == pytest.approx(np.sqrt((standalone ** 2).sum()))


def test_scr_is_three_sigma_times_volume(model):
    assert model.scr == pytest.approx(3 * model.sigma_company * model.total_volume)


# -------------------------------------------------------------- allocation
def test_euler_allocation_is_additive(model):
    allocation = model.euler_allocation()
    assert allocation["scr_allocated"].sum() == pytest.approx(model.scr, rel=1e-12)


def test_every_segment_receives_a_diversification_credit(model):
    allocation = model.euler_allocation()
    assert (allocation["diversification_credit"] > 0).all()
    assert (allocation["scr_allocated"] < allocation["scr_standalone"]).all()


def test_allocation_shares_sum_to_one(model):
    assert model.euler_allocation()["share_of_total"].sum() == pytest.approx(1.0)


def test_perfectly_correlated_allocation_equals_standalone(data):
    inputs, corr = data
    ones = pd.DataFrame(np.ones_like(corr.to_numpy()),
                        index=corr.index, columns=corr.columns)
    allocation = PremiumReserveRisk(inputs.copy(), ones).euler_allocation()
    assert np.allclose(allocation["scr_allocated"],
                       allocation["scr_standalone"], rtol=1e-9)


# ----------------------------------------------------------------- reliefs
def test_geographic_diversification_reduces_the_charge(data):
    inputs, corr = data
    geography = pd.read_csv(ROOT / "data" / "geographic_diversification.csv")
    div = geographic_diversification_factor(geography)
    base = PremiumReserveRisk(inputs.copy(), corr.copy())
    relieved = PremiumReserveRisk(inputs.copy(), corr.copy(), diversification=div)
    assert relieved.scr < base.scr


def test_div_factor_is_one_for_a_single_region():
    """A segment written entirely in one region earns no geographical credit."""
    shares = pd.DataFrame([{"lob_code": "X", "region": "Italy",
                            "premium_share": 1.0, "reserve_share": 1.0}])
    assert geographic_diversification_factor(shares)["X"] == pytest.approx(1.0)


def test_div_factor_is_bounded_by_the_number_of_regions():
    """Four equal regions give the minimum attainable DIV of 0.25."""
    shares = pd.DataFrame([{"lob_code": "X", "region": r,
                            "premium_share": 0.25, "reserve_share": 0.25}
                           for r in "ABCD"])
    assert geographic_diversification_factor(shares)["X"] == pytest.approx(0.25)


def test_np_adjustment_only_touches_eligible_segments(data):
    inputs, corr = data
    base = PremiumReserveRisk(inputs.copy(), corr.copy())
    adjusted = PremiumReserveRisk(inputs.copy(), corr.copy(),
                                  apply_np_adjustment=True)
    eligible = inputs.set_index("lob_code")["np_eligible"].astype(bool)
    for code in inputs["lob_code"]:
        before = base.segments.loc[code, "sigma_premium_adj"]
        after = adjusted.segments.loc[code, "sigma_premium_adj"]
        if eligible[code]:
            assert after == pytest.approx(before * 0.80)
        else:
            assert after == pytest.approx(before)


def test_volume_scalar_stays_within_the_regulatory_band(data):
    """The geographical factor can reduce the volume measure by at most 25%."""
    inputs, corr = data
    geography = pd.read_csv(ROOT / "data" / "geographic_diversification.csv")
    div = geographic_diversification_factor(geography)
    model = PremiumReserveRisk(inputs.copy(), corr.copy(), diversification=div)
    assert (model.segments["volume_scalar"] >= 0.75 - 1e-12).all()
    assert (model.segments["volume_scalar"] <= 1.0 + 1e-12).all()


# --------------------------------------------------------------- sensitivity
def test_more_premium_means_more_capital(model):
    up = model.with_shocked_volume("MTPL", 1.10)
    down = model.with_shocked_volume("MTPL", 0.90)
    assert down.scr < model.scr < up.scr


def test_the_largest_segment_moves_the_scr_the_most(model):
    swings = {code: (model.with_shocked_volume(code, 1.10).scr
                     - model.with_shocked_volume(code, 0.90).scr)
              for code in model.inputs["lob_code"]}
    assert max(swings, key=swings.get) == "MTPL"


def test_herfindahl_bounds():
    assert herfindahl_index(np.array([1.0])) == pytest.approx(1.0)
    assert herfindahl_index(np.array([0.25] * 4)) == pytest.approx(0.25)
