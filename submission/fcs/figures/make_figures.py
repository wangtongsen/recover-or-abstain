#!/usr/bin/env python3
"""Regenerate the FCS submission figures in every format the journal may require.

Outputs (per figure): PDF (vector), EPS (vector, journal-preferred), TIFF 600 dpi, PNG 600 dpi.

Run:
  /Users/infoflow/.workbuddy/binaries/python/envs/default/bin/python submission/fcs/figures/make_figures.py
"""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams.update({'font.family': 'DejaVu Sans'})
OUT = Path(__file__).resolve().parent


def save_all(fig, stem):
    """Write every format the journal may ask for.

    TIFF is re-encoded with LZW compression: matplotlib writes it uncompressed,
    which pushes a 600 dpi render well past the journal's 20 MB per-file limit.
    """
    from PIL import Image

    fig.savefig(OUT / f"{stem}.pdf", bbox_inches='tight')
    fig.savefig(OUT / f"{stem}.eps", bbox_inches='tight')
    fig.savefig(OUT / f"{stem}.png", bbox_inches='tight', dpi=600)
    tiff = OUT / f"{stem}.tiff"
    fig.savefig(tiff, bbox_inches='tight', dpi=600)
    Image.open(tiff).save(tiff, compression='tiff_lzw')
    plt.close(fig)


# ---------------------------------------------------------------- Fig. 1
def figure1():
    fig, ax = plt.subplots(figsize=(9.8, 4.4), dpi=300)
    ax.set_xlim(0, 17.4)
    ax.set_ylim(0, 9.9)
    ax.axis('off')

    def box(x, y, w, h, text, fc='#EAF1F8', ec='#3B6E9E', fs=7.9):
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                                    boxstyle="round,pad=0.04,rounding_size=0.10",
                                    linewidth=1.0, edgecolor=ec, facecolor=fc))
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center',
                fontsize=fs, linespacing=1.4)

    def arrow(p1, p2, color='#333333', ls='-', lw=1.0, rad=0.0):
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle='-|>', linestyle=ls, color=color,
                                     linewidth=lw, mutation_scale=10,
                                     connectionstyle=f"arc3,rad={rad}"))

    MY, MH = 5.8, 1.4
    box(0.30, MY, 2.55, MH, "Source trajectory $\\tau$\n(fault injected)")
    box(3.20, MY, 2.25, MH, "Public-evidence\ndiagnosis")
    box(5.80, MY, 1.85, MH, "Risk\u2013utility\ngating")
    box(8.00, MY, 3.10, MH, "Isolated counterfactual\nreplay (clean session)")
    box(11.85, 7.40, 4.45, 1.40, "Replay veto\nabstain \u00b7 patch NOT committed",
        fc='#FBECEA', ec='#B4534B')
    box(11.85, 3.60, 4.45, 1.40, "Admitted recovery\ncommit with strict receipt",
        fc='#E8F3EC', ec='#3F7D57')
    ax.text(12.00, 6.50, "replay predicts\nside effect or\nfailure", fontsize=6.8,
            color='#B4534B', ha='left', va='center', linespacing=1.35)

    ax.add_patch(FancyBboxPatch((0.30, 0.95), 16.80, 1.95,
                                boxstyle="round,pad=0.04,rounding_size=0.10",
                                linewidth=1.0, edgecolor='#8A8A85', facecolor='#F4F4F2'))
    ax.text(0.62, 2.52, "Fail-closed admission audit  (applied to every record)",
            fontsize=7.4, ha='left', va='center', weight='bold', color='#444441')
    ax.text(0.62, 1.95, "G1 source anchor \u00b7 G2 paired identity \u00b7 G3 strict replay receipt \u00b7 G4 side-effect witness",
            fontsize=6.8, ha='left', va='center', color='#444441')
    ax.text(0.62, 1.50, "G5 leakage scan \u00b7 G6 domain/scenario + oracle label \u00b7 G7 envelope & dedup     |     G0 protocol/matrix/model lock \u00b7 G8 plan\u2013execution coverage",
            fontsize=6.8, ha='left', va='center', color='#444441')

    arrow((2.85, 6.50), (3.20, 6.50))
    arrow((5.45, 6.50), (5.80, 6.50))
    arrow((7.65, 6.50), (8.00, 6.50))
    arrow((11.10, 6.78), (11.85, 7.95))
    arrow((11.10, 6.22), (11.85, 4.35))
    arrow((14.07, 7.40), (14.07, 5.05), color='#B4534B', ls='--')
    arrow((6.80, 7.20), (13.05, 8.80), color='#B4534B', ls='--', rad=-0.30)
    ax.text(9.95, 9.45, "veto feedback: the policy abstains and the patch is never committed",
            fontsize=6.8, color='#B4534B', ha='center', va='center')
    arrow((14.07, 3.60), (14.07, 2.92), color='#3F7D57')
    ax.text(14.25, 3.26, "admitted\nrecords", fontsize=6.6, color='#3F7D57',
            ha='left', va='center', linespacing=1.3)

    save_all(fig, 'fig1-racer-loop')


# ---------------------------------------------------------------- Fig. 2
def figure2():
    labels = ["S1 (flight, omission)", "S2 (flight, price corruption)",
              "S3 (hotel, omission)", "S4 (shop, stock falsification)",
              "S5 (hotel, stale quote)", "S6 (shop, omission)",
              "S7 (flight, stale quote)"]
    retry_glm = [87.5, 87.5, 100.0, 87.5, 87.5, 87.5, 100.0]
    nocf_glm = [100.0] * 7
    retry_ds = [87.5, 87.5, 100.0, 87.5, 52.5, 87.5, 80.0]
    nocf_ds = [100.0, 100.0, 100.0, 100.0, 60.0, 100.0, 80.0]
    racer = [0.0] * 7

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.4), dpi=300, sharey=True)
    y = np.arange(7)
    for ax, retry, nocf, title in ((axes[0], retry_glm, nocf_glm, "GLM-5.3-Flash (primary model)"),
                                   (axes[1], retry_ds, nocf_ds, "DeepSeek-V4-Flash (replication)")):
        for i in range(7):
            ax.plot([0, max(retry[i], nocf[i])], [y[i], y[i]], color='#CFCFCB',
                    linewidth=1.2, zorder=1)
        ax.scatter(nocf, y, s=42, marker='s', color='#D98A3D', edgecolor='#8F5618',
                   linewidth=0.6, zorder=3, label='RACER\u2212counterfactual (no verification)')
        ax.scatter(retry, y, s=46, marker='o', color='#B4534B', edgecolor='#7C3A34',
                   linewidth=0.6, zorder=3, label='Non-verifying baselines (8)')
        ax.scatter(racer, y, s=52, marker='D', color='#3F7D57', edgecolor='#2C5A3E',
                   linewidth=0.6, zorder=4, label='RACER (replay veto)')
        for i in range(7):
            ax.annotate('0', (0, y[i]), textcoords='offset points', xytext=(0, -11),
                        ha='center', fontsize=6.8, color='#2C5A3E', zorder=5)
        ax.set_title(title, fontsize=8.8, pad=6)
        ax.set_xlim(-7, 112)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels(['0', '25', '50', '75', '100'], fontsize=7.5)
        ax.set_ylim(6.7, -0.8)
        ax.set_xlabel('Harmful-commit rate (%)', fontsize=8.2)
        ax.grid(axis='x', linestyle=':', linewidth=0.5, color='#BBBBBB')
        ax.set_axisbelow(True)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels, fontsize=7.6)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc='lower center', ncol=3, frameon=False, fontsize=7.6,
               bbox_to_anchor=(0.5, -0.03))
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    save_all(fig, 'fig2-scenario-separation')


if __name__ == '__main__':
    figure1()
    figure2()
    print('figures written to', OUT)
