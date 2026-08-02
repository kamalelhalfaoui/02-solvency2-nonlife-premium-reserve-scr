"""Export the Power BI star schema for the underwriting risk dashboard."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scr import PremiumReserveRisk, geographic_diversification_factor  # noqa: E402

OUT = Path(__file__).parent / "model"
OUT.mkdir(exist_ok=True)

inputs = pd.read_csv(ROOT / "data" / "lob_inputs.csv")
corr = pd.read_csv(ROOT / "data" / "correlation_matrix.csv", index_col=0)
geography = pd.read_csv(ROOT / "data" / "geographic_diversification.csv")
div = geographic_diversification_factor(geography)

base = PremiumReserveRisk(inputs.copy(), corr.copy())
geo = PremiumReserveRisk(inputs.copy(), corr.copy(), diversification=div)
npr = PremiumReserveRisk(inputs.copy(), corr.copy(), apply_np_adjustment=True)
both = PremiumReserveRisk(inputs.copy(), corr.copy(), diversification=div,
                          apply_np_adjustment=True)

# --- Dimensions --------------------------------------------------------------
dim_lob = inputs[["lob_code", "lob_name", "np_eligible"]].copy()
dim_lob["RiskFamily"] = dim_lob["lob_code"].map(
    {"MTPL": "Motor", "MOTOR_OTHER": "Motor", "FIRE": "Property",
     "GL": "Liability", "LEGAL": "Liability"})
dim_lob.columns = ["LobCode", "LobName", "NPEligible", "RiskFamily"]
dim_lob.to_csv(OUT / "dim_lob.csv", index=False)

pd.DataFrame({
    "ScenarioKey": [1, 2, 3, 4],
    "Scenario": ["No reliefs", "Geographical diversification",
                 "Non-proportional reinsurance", "Both reliefs"],
    "AppliesGeographic": [False, True, False, True],
    "AppliesNP": [False, False, True, True],
}).to_csv(OUT / "dim_scenario.csv", index=False)

geography.rename(columns={"lob_code": "LobCode", "region": "Region",
                          "premium_share": "PremiumShare",
                          "reserve_share": "ReserveShare"}
                 ).to_csv(OUT / "dim_region.csv", index=False)

# --- Facts -------------------------------------------------------------------
frames = []
for key, model in enumerate([base, geo, npr, both], start=1):
    volumes = model.volume_table()
    allocation = model.euler_allocation()
    merged = volumes.merge(allocation[["lob_code", "scr_allocated",
                                       "diversification_credit",
                                       "share_of_total"]], on="lob_code")
    merged["ScenarioKey"] = key
    frames.append(merged)

fact = pd.concat(frames, ignore_index=True)
fact.columns = ["LobCode", "LobName", "VPremium", "VReserve", "VTotal",
                "SigmaPremium", "SigmaReserve", "SigmaLob", "ScrStandalone",
                "ScrAllocated", "DiversificationCredit", "ShareOfTotal",
                "ScenarioKey"]
fact.to_csv(OUT / "fact_scr_by_lob.csv", index=False)

pd.DataFrame([
    dict(ScenarioKey=key, **model.summary())
    for key, model in enumerate([base, geo, npr, both], start=1)
]).rename(columns={
    "total_volume": "TotalVolume", "sigma_company": "SigmaCompany",
    "scr_diversified": "ScrDiversified", "scr_undiversified": "ScrUndiversified",
    "diversification_benefit": "DiversificationBenefit",
    "diversification_benefit_pct": "DiversificationBenefitPct",
}).to_csv(OUT / "fact_scr_summary.csv", index=False)

long_corr = corr.stack().reset_index()
long_corr.columns = ["LobCodeI", "LobCodeJ", "Correlation"]
long_corr.to_csv(OUT / "fact_correlation.csv", index=False)

div.reset_index().rename(columns={"lob_code": "LobCode",
                                  "div_factor": "DivFactor"}
                         ).assign(VolumeScalar=lambda d: 0.75 + 0.25 * d.DivFactor
                                  ).to_csv(OUT / "fact_geographic_div.csv", index=False)

sensitivity = pd.DataFrame([
    {"LobCode": code,
     "ScrDown10": base.with_shocked_volume(code, 0.90).scr,
     "ScrBase": base.scr,
     "ScrUp10": base.with_shocked_volume(code, 1.10).scr}
    for code in inputs["lob_code"]])
sensitivity.to_csv(OUT / "fact_sensitivity.csv", index=False)

print(f"Star schema written to {OUT}")
for path in sorted(OUT.glob("*.csv")):
    print(f"  {path.name:<28} {len(pd.read_csv(path)):>4} rows")
