"""참고 read (no selection): the rule bot ranking the owners sent on 10/23 (30m / 1h rows only; 4h and 15m rows are not in
round 3's outcome set). Each strategy at the rule bot's form (2 ATR + its ladder, 9x, every day, one position) over
2020-03 .. 2026-09: win rate against the break-even win rate, net per trade, how often a run of the same number of trades
reached the screen's return and what came after, and direction skill against a coin on 2025-26.

    python3 -I vwrank2.py   -> research/vwap30/rank1023.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwtwo import *

ROWS = [("V39_ALL_at_1h", "V3.9 1시간", 0.587, 23), ("N05_PSAR_POC_at_30m", "PSAR·POC 캔들 30분", 0.448, 24),
        ("S3_CMO_SANDWICH_at_30m", "CMO·샌드위치 캔들 30분", 0.409, 20), ("OBV_S_at_30m", "OBV 추세형 30분", 0.381, 29),
        ("N13_3OUTSIDE_at_30m", "쓰리 아웃사이드 30분", 0.225, 35), ("S3_CMO_SANDWICH_at_1h", "CMO·샌드위치 캔들 1시간", 0.21, 14),
        ("N03_ADX_GC_at_30m", "ADX·골든크로스 30분", 0.121, 6), ("S6_EMA_DMI_ADX_at_1h", "EMA·DMI·ADX 1시간", 0.111, 12),
        ("S2_ST_ROC_at_1h", "슈퍼트렌드·ROC 1시간", 0.099, 43), ("N12_ICHI_AO_at_1h", "일목·AO 1시간", 0.088, 17)]


def main():
    out = {}
    for lab, ko, live_ret, k in ROWS:
        b = Label(lab).one(EX_HOUSE2)
        r = runs(b, live_ret, k)
        row = {"ko": ko, "screen_ret": live_ret, "screen_trades": k, **r,
               "confirm_rb9_mult": pick(metrics(b, all_mask(b), 0, "confirm", r="rb9"))["mult"],
               "twin_confirm": twin(b, "confirm")}
        out[lab] = row
        print(ko, "| win", r["win"], "BE", r["breakeven_win"], "net%", r["avg_net_pct"], "| runs>=screen", r["run_share_ge_live"],
              "next+", r["after_good_run_next_pos"], "| 25-26 vs coin", row["twin_confirm"]["share_below"], flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "rank1023.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
