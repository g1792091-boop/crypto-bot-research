"""Trade-by-trade: the bot-code replay (parity_replay_bybit.json) vs the sweep simulation of the same members (A gated to the
BTC 4h down regime) over the forward window."""
import os, sys, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SW = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/sweep2"
sys.path.insert(0, SW)
exec(open(os.path.join(SW, "s4_combo.py")).read().split("res = {}")[0])
from common import COINS                                  # noqa: E402

rep = json.load(open(os.path.join(HERE, "parity_replay_bybit.json")))
R = pd.DataFrame(rep["trades"])
print("replay trades", len(R), "columns", list(R.columns)[:30])
T = trades(gate(A, (1,)), None)
T = T[(T.t >= SM.FWD_A) & (T.t < SM.Z)].reset_index(drop=True)
T["symbol"] = np.asarray(COINS)[T.coin.to_numpy()]
T["exit_t"] = T.t + T.k * 60000
sim_x = float(np.prod(1 + T.w))
print("sim trades", len(T), "sim x", round(sim_x, 3))
R["entry_min"] = (R.entry_time // 60000) * 60000
eq0 = 1000.0
R = R.sort_values("exit_time").reset_index(drop=True)
rx = float((eq0 + R.pnl.sum()) / eq0) if len(R) else 1.0
R["wallet_ret"] = R.pnl / (eq0 + R.pnl.cumsum().shift(fill_value=0.0))
print("replay x (equity_after / 1000):", round(rx, 3))
key_s = set(zip(T.t, T.symbol, T.side))
key_r = set(zip(R.entry_min, R.symbol, R.side))
both = key_s & key_r
print("matched entries", len(both), "| sim only", len(key_s - key_r), "| replay only", len(key_r - key_s))
M = T.merge(R, left_on=["t", "symbol", "side"], right_on=["entry_min", "symbol", "side"], how="outer", indicator=True,
            suffixes=("_sim", "_rep"))
cols = [c for c in ("symbol", "side", "member_sim", "member_rep", "w", "wallet_ret", "exit_t", "exit_time", "reason", "roe", "_merge") if c in M.columns]
pd.set_option("display.width", 250)
M["t_kst"] = pd.to_datetime(M.t.fillna(M.entry_min) + 9 * 3600 * 1000, unit="ms").dt.strftime("%m-%d %H:%M")
print(M[["t_kst"] + cols].to_string())
M.to_csv(os.path.join(HERE, "compare_bybit.csv"), index=False)
