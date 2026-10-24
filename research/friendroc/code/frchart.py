"""PREREG3 "14패 하나하나": one picture of the 14 October losses of P (frdeep.py writes OUT/oct_taken.pkl first). Each panel:
the coin and BTC from 6 h before the entry to 2 h after the exit, both as % from their entry-minute open turned to the trade's
side (up = the trade's way), the -50 % stop (-1.54 %) and the +12 % trigger of the first lock (+0.52 %), the holding time shaded.

    python3 -I frdeep.py && python3 -I frchart.py     -> OUT/loss14.png (session scratchpad, not in the repository)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frloss import LEV, COST, FL, GAP
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

SURFACE, INK, INK2, GRIDC, SHADE = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#f0efec"
COIN_C, BTC_C = "#2a78d6", "#eb6834"                      # categorical slots 1 and 2 (validated, light)
STOP = -(0.5 / LEV - COST) * 100
TRIG = ((FL + GAP) / LEV + COST) * 100


def main():
    for f in font_manager.findSystemFonts():
        if "wqy-zenhei" in f:
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
    plt.rcParams.update({"axes.unicode_minus": False, "font.size": 9})
    D = pd.read_pickle(os.path.join(OUT, "oct_taken.pkl"))
    L = D[D.roe <= 0].reset_index(drop=True)
    bt = grid("BTCUSDT")
    fig, axs = plt.subplots(5, 3, figsize=(12, 15.5), facecolor=SURFACE)
    for q, ax in enumerate(axs.flat):
        ax.set_facecolor(SURFACE)
        for sp in ax.spines.values():
            sp.set_color(GRIDC)
        if q >= len(L):
            continue
        r = L.iloc[q]
        g = grid(COINS[int(r.coin)])
        e, s, k = int(r.e), int(r.side), int(r.minutes) - 1
        a, z = e - 6 * 60, min(e + k + 120, g["n"] - 1)
        x = np.arange(a, z + 1, 5)
        hrs = (x - e) / 60
        cp = s * (g["c"][x] / g["o"][e] - 1) * 100
        bp = s * (bt["c"][x] / bt["o"][e] - 1) * 100
        ax.axvspan(0, (k + 1) / 60, color=SHADE, zorder=0)
        for y, lab in ((STOP, "손절 -50%"), (TRIG, "+12% (첫 잠금 자리)")):
            ax.axhline(y, color=INK2, lw=0.8, zorder=1)
            ax.text(hrs[0], y, " " + lab, color=INK2, fontsize=7, va="bottom", ha="left", zorder=5,
                    bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85, "pad": 0.6})
        ax.axhline(0, color=GRIDC, lw=1, zorder=1)
        ax.plot(hrs, bp, color=BTC_C, lw=1.6, zorder=2, solid_capstyle="round")
        ax.plot(hrs, cp, color=COIN_C, lw=2, zorder=3, solid_capstyle="round")
        xe = s * (g["c"][min(e + k, g["n"] - 1)] / g["o"][e] - 1) * 100
        ax.scatter([(k + 1) / 60], [xe], s=30, color=COIN_C, edgecolor=SURFACE, linewidth=2, zorder=4)
        lo = min(cp.min(), bp.min(), STOP) - 0.3
        hi = max(cp.max(), bp.max(), TRIG) + 0.3
        ax.set_ylim(lo, hi)
        ax.set_xlim(hrs[0], hrs[-1])
        ax.tick_params(colors=INK2, labelsize=7, length=0)
        ax.grid(axis="y", color=GRIDC, lw=0.6)
        kst = pd.Timestamp(int(r.t) + KST, unit="ms")
        hold = f"{k + 1}분" if k + 1 < 120 else f"{(k + 1) / 60:.1f}시간"
        end = "열려 있음" if r.roe > -0.45 else "손절"
        ax.set_title(f"{q + 1}. {kst:%m/%d %H:%M} {COINS[int(r.coin)][:-4]} {'롱' if s > 0 else '숏'} · {hold} · {end}\n"
                     f"BTC {r.btc_with_pct:+.2f}% · 최고 순ROE {r.mfe_roe:+.1f}%", fontsize=8.5, color=INK, loc="left")
        if q % 3 == 0:
            ax.set_ylabel("진입가 대비 % (거래 방향 기준)", color=INK2, fontsize=7)
        if q >= 11:
            ax.set_xlabel("진입 뒤 시간(시간)", color=INK2, fontsize=7)
    ax = axs.flat[-1]
    ax.axis("off")
    ax.plot([0.05, 0.2], [0.78, 0.78], color=COIN_C, lw=2.5, transform=ax.transAxes)
    ax.text(0.24, 0.78, "그 코인 (위 = 거래 방향으로 감)", va="center", transform=ax.transAxes, color=INK)
    ax.plot([0.05, 0.2], [0.64, 0.64], color=BTC_C, lw=2, transform=ax.transAxes)
    ax.text(0.24, 0.64, "BTC (같은 방향 기준)", va="center", transform=ax.transAxes, color=INK)
    ax.add_patch(plt.Rectangle((0.05, 0.46), 0.15, 0.08, color=SHADE, transform=ax.transAxes))
    ax.text(0.24, 0.50, "들고 있던 시간", va="center", transform=ax.transAxes, color=INK)
    ax.text(0.05, 0.30, "10월 친구 매매법(P) 진 거래 14번\n한국 시간 · 30배 · 왕복 비용 0.124% 포함\n진입 6시간 전 ~ 나간 뒤 2시간",
            va="center", transform=ax.transAxes, color=INK2, fontsize=8)
    fig.tight_layout(h_pad=1.6)
    path = os.path.join(OUT, "loss14.png")
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    print(path)


if __name__ == "__main__":
    main()
