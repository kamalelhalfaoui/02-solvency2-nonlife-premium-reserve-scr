"""Chart production for the premium and reserve risk module."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

NAVY = "#1B2A4A"
TEAL = "#2E7D8F"
AMBER = "#C8853A"
CRIMSON = "#A33C3C"
SAGE = "#6B8E5A"
GREY = "#8A8F98"
PALETTE = [NAVY, TEAL, AMBER, SAGE, CRIMSON]


def apply_style() -> None:
    plt.rcParams.update({
        "figure.dpi": 140, "savefig.dpi": 140,
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
        "axes.labelcolor": "#3A4050", "axes.edgecolor": "#C9CDD4",
        "axes.grid": True, "axes.axisbelow": True,
        "grid.color": "#E4E7EC", "grid.linewidth": 0.7,
        "xtick.color": "#5A616E", "ytick.color": "#5A616E",
        "legend.frameon": False, "figure.facecolor": "white",
        "axes.spines.top": False, "axes.spines.right": False,
    })


def plot_volume_measures(volumes, path) -> None:
    apply_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3),
                                   gridspec_kw={"width_ratios": [1.5, 1]})
    x = np.arange(len(volumes))
    ax1.bar(x, volumes["v_premium"] / 1e6, color=NAVY, width=0.6,
            label="Premium volume $V_{prem}$")
    ax1.bar(x, volumes["v_reserve"] / 1e6, bottom=volumes["v_premium"] / 1e6,
            color=TEAL, width=0.6, label="Reserve volume $V_{res}$")
    for i, row in volumes.reset_index(drop=True).iterrows():
        ax1.text(i, row["v_total"] / 1e6 * 1.02, f"{row['v_total'] / 1e6:,.0f}",
                 ha="center", fontsize=8, fontweight="bold", color=NAVY)
    ax1.set_xticks(x)
    ax1.set_xticklabels(volumes["lob_code"], rotation=20, ha="right")
    ax1.set_ylabel("EUR m")
    ax1.set_title("Volume measure by segment")
    ax1.legend(fontsize=8)

    bars = ax2.barh(volumes["lob_code"], volumes["sigma_lob"] * 100,
                    color=PALETTE, height=0.6)
    for bar, value in zip(bars, volumes["sigma_lob"] * 100):
        ax2.text(value + 0.08, bar.get_y() + bar.get_height() / 2,
                 f"{value:.2f}%", va="center", fontsize=8.5,
                 fontweight="bold", color=NAVY)
    ax2.set_xlabel("Combined volatility $\\sigma_{LoB}$ (%)")
    ax2.set_title("Segment volatility")
    ax2.margins(x=0.18)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_correlation_matrix(corr, path) -> None:
    apply_style()
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    data = corr.to_numpy()
    im = ax.imshow(data, cmap="Blues", vmin=0, vmax=1)
    for i in range(len(corr)):
        for j in range(len(corr)):
            colour = "white" if data[i, j] > 0.6 else NAVY
            ax.text(j, i, f"{data[i, j]:.2f}", ha="center", va="center",
                    fontsize=8.5, color=colour)
    ax.set_xticks(range(len(corr)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(corr)))
    ax.set_yticklabels(corr.index, fontsize=8)
    ax.set_title("Segment correlation matrix")
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_diversification_waterfall(summary, path) -> None:
    """Standalone charges stepping down to the diversified requirement."""
    apply_style()
    undiv = summary["scr_undiversified"] / 1e6
    benefit = summary["diversification_benefit"] / 1e6
    div = summary["scr_diversified"] / 1e6

    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    labels = ["Sum of\nstandalone", "Diversification\nbenefit", "Diversified\nSCR"]
    ax.bar(0, undiv, color=NAVY, width=0.55)
    ax.bar(1, benefit, bottom=div, color=SAGE, width=0.55)
    ax.bar(2, div, color=TEAL, width=0.55)
    ax.plot([0.28, 0.72], [undiv, undiv], color=GREY, ls=":", lw=1.2)
    ax.plot([1.28, 1.72], [div, div], color=GREY, ls=":", lw=1.2)

    ax.text(0, undiv * 1.02, f"{undiv:,.1f}", ha="center", fontweight="bold",
            color=NAVY, fontsize=10)
    ax.text(1, (div + benefit / 2), f"−{benefit:,.1f}\n({summary['diversification_benefit_pct']:.1%})",
            ha="center", va="center", fontweight="bold", color="white", fontsize=9.5)
    ax.text(2, div * 1.02, f"{div:,.1f}", ha="center", fontweight="bold",
            color=NAVY, fontsize=10)

    ax.set_xticks(range(3))
    ax.set_xticklabels(labels)
    ax.set_ylabel("EUR m")
    ax.set_title("Diversification benefit across segments")
    ax.set_ylim(0, undiv * 1.14)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_capital_allocation(allocation, path) -> None:
    """Standalone versus Euler-allocated capital by segment."""
    apply_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3),
                                   gridspec_kw={"width_ratios": [1.6, 1]})
    x = np.arange(len(allocation))
    width = 0.38
    ax1.bar(x - width / 2, allocation["scr_standalone"] / 1e6, width,
            color=NAVY, label="Standalone")
    ax1.bar(x + width / 2, allocation["scr_allocated"] / 1e6, width,
            color=TEAL, label="Euler-allocated")
    for i, row in allocation.reset_index(drop=True).iterrows():
        ax1.text(i + width / 2, row["scr_allocated"] / 1e6 * 1.02,
                 f"−{row['credit_pct']:.0%}", ha="center", fontsize=7.5,
                 color=SAGE, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(allocation["lob_code"], rotation=20, ha="right")
    ax1.set_ylabel("EUR m")
    ax1.set_title("Capital charge: standalone vs. diversified allocation")
    ax1.legend(fontsize=8)

    ax2.pie(allocation["share_of_total"], labels=allocation["lob_code"],
            autopct="%1.1f%%", colors=PALETTE, startangle=90,
            textprops={"fontsize": 8},
            wedgeprops={"edgecolor": "white", "linewidth": 1.5})
    ax2.set_title("Share of diversified SCR")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_sensitivity_tornado(sensitivity, base_scr, path) -> None:
    """Effect on the SCR of a +/-10% change in each segment's premium volume."""
    apply_style()
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    order = sensitivity.reindex(
        sensitivity["up"].sub(sensitivity["down"]).abs().sort_values().index)
    y = np.arange(len(order))
    down = (order["down"] - base_scr) / 1e6
    up = (order["up"] - base_scr) / 1e6
    ax.barh(y, down, color=TEAL, height=0.58, label="Premium volume −10%")
    ax.barh(y, up, color=AMBER, height=0.58, label="Premium volume +10%")
    for i, (d, u) in enumerate(zip(down, up)):
        ax.text(u + 0.12, i, f"{u:+.2f}", va="center", fontsize=7.8, color=NAVY)
        ax.text(d - 0.12, i, f"{d:+.2f}", va="center", ha="right",
                fontsize=7.8, color=NAVY)
    ax.axvline(0, color=NAVY, lw=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels(order["lob_code"])
    ax.set_xlabel("Change in diversified SCR (EUR m)")
    ax.set_title("Sensitivity of the SCR to premium volume by segment")
    ax.legend(fontsize=8, loc="lower right")
    ax.margins(x=0.16)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_scenario_ladder(scenarios, path) -> None:
    """SCR under each combination of the optional regulatory reliefs."""
    apply_style()
    fig, ax = plt.subplots(figsize=(8.4, 4.2))
    labels = list(scenarios)
    values = [v / 1e6 for v in scenarios.values()]
    colours = [NAVY, TEAL, AMBER, SAGE][:len(labels)]
    bars = ax.bar(labels, values, color=colours, width=0.58)
    baseline = values[0]
    for bar, value in zip(bars, values):
        delta = (value / baseline - 1) * 100
        label = f"{value:,.1f}" + ("" if abs(delta) < 1e-9 else f"\n({delta:+.1f}%)")
        ax.text(bar.get_x() + bar.get_width() / 2, value * 1.015, label,
                ha="center", fontsize=8.5, fontweight="bold", color=NAVY)
    ax.set_ylabel("Diversified SCR (EUR m)")
    ax.set_title("Effect of the optional standard-formula reliefs")
    ax.set_ylim(0, max(values) * 1.18)
    plt.setp(ax.get_xticklabels(), rotation=12, ha="right")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
