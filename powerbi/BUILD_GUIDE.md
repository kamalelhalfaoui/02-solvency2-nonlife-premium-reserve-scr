# Power BI — Non-Life Underwriting Risk dashboard

`.pbix` is a proprietary binary container, so this folder ships the model
instead: dimensional CSVs in `model/`, the measure library in `measures.dax`,
and the layout below.

## 1. Generate and import

```bash
python powerbi/build_model.py
```

**Home → Get Data → Text/CSV** for each file in `model/`. Confirm `LobCode`
imports as *Text* and every monetary column as *Decimal Number*.

## 2. Star schema

```
   dim_scenario                dim_region
        │ 1                         │ 1
        ▼ *                         ▼ *
   fact_scr_by_lob  ◄──*── dim_lob ──*──►  fact_geographic_div
        ▲                    │ 1
        │                    ├──*──► fact_sensitivity
   fact_scr_summary          └──*──► fact_correlation (LobCodeI)
```

| From | To | Cardinality |
|---|---|---|
| `dim_lob[LobCode]` | `fact_scr_by_lob[LobCode]` | 1 → * |
| `dim_lob[LobCode]` | `fact_sensitivity[LobCode]` | 1 → * |
| `dim_lob[LobCode]` | `fact_geographic_div[LobCode]` | 1 → * |
| `dim_lob[LobCode]` | `fact_correlation[LobCodeI]` | 1 → * |
| `dim_lob[LobCode]` | `dim_region[LobCode]` | 1 → * |
| `dim_scenario[ScenarioKey]` | `fact_scr_by_lob[ScenarioKey]` | 1 → * |
| `dim_scenario[ScenarioKey]` | `fact_scr_summary[ScenarioKey]` | 1 → * |

`fact_correlation[LobCodeJ]` must stay **unrelated** — a second active
relationship to `dim_lob` would create an ambiguous path. Leave it inactive, or
build a `dim_lob_j` copy if you want to slice the matrix on both axes.

## 3. Report pages

### Page 1 — Capital Summary
| Visual | Type | Fields |
|---|---|---|
| KPI row | 4 × Card | `SCR Headline`, `Company Sigma`, `Benefit Headline`, `Capital Concentration` |
| Waterfall | Waterfall | Category `dim_lob[LobCode]`, breakdown `SCR Allocated` |
| Standalone vs allocated | Clustered column | Axis `LobCode`; values `SCR Standalone`, `SCR Allocated` |
| Relief ladder | Column | Axis `dim_scenario[Scenario]`, value `SCR Diversified` |
| Slicer | | `dim_lob[RiskFamily]` |

### Page 2 — Segment Detail
| Visual | Type | Fields |
|---|---|---|
| Volume split | Stacked column | Axis `LobCode`; `Premium Volume`, `Reserve Volume` |
| Volatility | Bar | Axis `LobCode`, value `Segment Sigma` |
| Capital intensity | Scatter | X `Total Volume`, Y `Capital Intensity`, size `SCR Allocated`, legend `RiskFamily` |
| Correlation | Matrix | Rows `LobCodeI`, columns `LobCodeJ`, values `AVERAGE(Correlation)`, background conditional formatting |

### Page 3 — Sensitivity and Geography
| Visual | Type | Fields |
|---|---|---|
| Tornado | Clustered bar | Axis `LobCode`; `SCR Sensitivity Down`, `SCR Sensitivity Up` |
| Regional mix | Stacked bar 100% | Axis `LobCode`, legend `Region`, value `SUM(PremiumShare)` |
| DIV factors | Table | `LobCode`, `Regions Written`, `DIV Factor`, `Volume Scalar` |

## 4. Three traps worth avoiding

**Never average the segment sigma column to get a company figure.** Correlation
aggregation is a quadratic form, so the company sigma is not any kind of mean of
the parts. `Company Sigma` derives it from `SCR / (3 × V)` for that reason. A
simple `AVERAGE(SigmaLob)` here returns roughly 8.2% against a true 5.99% — a
37% overstatement, and an easy one to ship unnoticed.

**`SCR Diversified` uses `SUMX` over scenario, not a plain `SUM`.** With no
scenario filter applied, a plain sum would add all four bases together. Iterating
the scenario key keeps the measure correct at every grain.

**Allocated capital is additive; standalone capital is not.** `SCR Allocated`
totals to the diversified requirement at any level of the hierarchy, which is
exactly why the Euler allocation is worth computing. `SCR Standalone` sums to a
number the firm never has to hold — useful as a reference point, misleading as a
subtotal.
