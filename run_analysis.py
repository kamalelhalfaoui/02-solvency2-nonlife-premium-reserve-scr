"""
Aurelia Assicurazioni S.p.A. — non-life premium and reserve risk SCR.

Computes the standard-formula charge on four bases (gross, with geographical
diversification, with the non-proportional reinsurance adjustment, and both),
allocates the diversified requirement back to segment, and runs a premium
volume sensitivity.

    python run_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from scr import PremiumReserveRisk, geographic_diversification_factor  # noqa: E402
from scr import viz  # noqa: E402

DATA = ROOT / "data"
TABLES = ROOT / "outputs" / "tables"
FIGURES = ROOT / "outputs" / "figures"


def banner(text: str) -> None:
    print(f"\n{text}\n{'=' * len(text)}")


def money(value: float) -> str:
    return f"EUR {value / 1e6:,.2f}m"


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    inputs = pd.read_csv(DATA / "lob_inputs.csv")
    correlation = pd.read_csv(DATA / "correlation_matrix.csv", index_col=0)
    geography = pd.read_csv(DATA / "geographic_diversification.csv")

    # ------------------------------------------------------- 1. base result
    banner("1. Volume measures and segment volatility")
    base = PremiumReserveRisk(inputs.copy(), correlation.copy())
    volumes = base.volume_table()
    display = volumes.assign(
        V_prem=lambda d: (d.v_premium / 1e6).round(1),
        V_res=lambda d: (d.v_reserve / 1e6).round(1),
        V_total=lambda d: (d.v_total / 1e6).round(1),
        sigma=lambda d: (d.sigma_lob * 100).round(2),
        SCR_standalone=lambda d: (d.scr_lob_standalone / 1e6).round(2),
    )[["lob_code", "V_prem", "V_res", "V_total", "sigma", "SCR_standalone"]]
    print(display.to_string(index=False))

    summary = base.summary()
    banner("2. Aggregation")
    print(f"Total volume measure V     : {money(summary['total_volume'])}")
    print(f"Company volatility sigma   : {summary['sigma_company']:.4%}")
    print(f"Sum of standalone charges  : {money(summary['scr_undiversified'])}")
    print(f"Diversified SCR (3·sigma·V): {money(summary['scr_diversified'])}")
    print(f"Diversification benefit    : {money(summary['diversification_benefit'])}"
          f"  ({summary['diversification_benefit_pct']:.1%})")

    # --------------------------------------------- 2. regulatory variations
    banner("3. Optional standard-formula reliefs")
    div_factors = geographic_diversification_factor(geography)
    print("Geographical diversification factor DIV by segment:")
    for code, value in div_factors.items():
        scalar = 0.75 + 0.25 * value
        print(f"  {code:<12} DIV = {value:.4f}   volume scalar = {scalar:.4f}")

    geo_model = PremiumReserveRisk(inputs.copy(), correlation.copy(),
                                   diversification=div_factors)
    np_model = PremiumReserveRisk(inputs.copy(), correlation.copy(),
                                  apply_np_adjustment=True)
    both_model = PremiumReserveRisk(inputs.copy(), correlation.copy(),
                                    diversification=div_factors,
                                    apply_np_adjustment=True)

    scenarios = {
        "No reliefs": base.scr,
        "Geographical\ndiversification": geo_model.scr,
        "Non-proportional\nreinsurance": np_model.scr,
        "Both": both_model.scr,
    }
    print()
    for name, value in scenarios.items():
        label = name.replace("\n", " ")
        print(f"  {label:<32} {money(value):>16}  "
              f"({value / base.scr - 1:+.1%})")

    # ------------------------------------------------------- 3. allocation
    banner("4. Euler allocation of the diversified charge")
    allocation = base.euler_allocation()
    print(allocation.assign(
        standalone=lambda d: (d.scr_standalone / 1e6).round(2),
        allocated=lambda d: (d.scr_allocated / 1e6).round(2),
        credit=lambda d: (d.credit_pct * 100).round(1),
        share=lambda d: (d.share_of_total * 100).round(1),
    )[["lob_code", "standalone", "allocated", "credit", "share"]]
        .to_string(index=False))
    print(f"\nAllocation reconciles to total: "
          f"{money(allocation['scr_allocated'].sum())} vs {money(base.scr)}")

    # ------------------------------------------------------ 4. sensitivity
    banner("5. Premium volume sensitivity (+/- 10%)")
    rows = []
    for code in inputs["lob_code"]:
        rows.append({
            "lob_code": code,
            "down": base.with_shocked_volume(code, 0.90).scr,
            "up": base.with_shocked_volume(code, 1.10).scr,
        })
    sensitivity = pd.DataFrame(rows)
    sensitivity["swing"] = sensitivity["up"] - sensitivity["down"]
    print(sensitivity.assign(
        down_m=lambda d: ((d["down"] - base.scr) / 1e6).round(3),
        up_m=lambda d: ((d["up"] - base.scr) / 1e6).round(3),
        swing_m=lambda d: (d.swing / 1e6).round(3),
    )[["lob_code", "down_m", "up_m", "swing_m"]].to_string(index=False))

    # ----------------------------------------------------------- outputs
    banner("Writing outputs")
    volumes.to_csv(TABLES / "volume_measures.csv", index=False)
    allocation.to_csv(TABLES / "capital_allocation.csv", index=False)
    sensitivity.to_csv(TABLES / "premium_sensitivity.csv", index=False)
    pd.DataFrame([{k: v for k, v in summary.items()}]).to_csv(
        TABLES / "scr_summary.csv", index=False)
    pd.DataFrame({"scenario": [s.replace("\n", " ") for s in scenarios],
                  "scr": list(scenarios.values())}).to_csv(
        TABLES / "relief_scenarios.csv", index=False)
    div_factors.rename("div_factor").to_frame().to_csv(
        TABLES / "geographic_div_factors.csv")

    viz.plot_volume_measures(volumes, FIGURES / "01_volume_measures.png")
    viz.plot_correlation_matrix(correlation, FIGURES / "02_correlation_matrix.png")
    viz.plot_diversification_waterfall(summary,
                                       FIGURES / "03_diversification_benefit.png")
    viz.plot_capital_allocation(allocation, FIGURES / "04_capital_allocation.png")
    viz.plot_sensitivity_tornado(sensitivity, base.scr,
                                 FIGURES / "05_premium_sensitivity.png")
    viz.plot_scenario_ladder(scenarios, FIGURES / "06_relief_scenarios.png")

    print(f"  {len(list(TABLES.glob('*.csv')))} tables  -> outputs/tables/")
    print(f"  {len(list(FIGURES.glob('*.png')))} figures -> outputs/figures/")
    print("\nDone.")


if __name__ == "__main__":
    main()
