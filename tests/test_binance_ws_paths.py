"""Binance moved its USD-M market WebSocket streams under /market (2026-10, checked on the server: the old /ws and
/stream paths accept the connection but send nothing; /market/... streams aggTrade and forceOrder). Every recorder
and page uses the new paths; and the Obsidian export survives the start day's daily3 report, whose parity part is a
plain note, not a dict (it failed with AttributeError on 10/06 09:50)."""
import os
import re

from paperbot import obsidian_sources as OS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
        return fh.read()


def test_no_old_silent_paths():
    for p in ("paperbot/liqstream.py", "paperbot/dash/more/ticks.py", "paperbot/dash/static/app.js", "paperbot/dash/static/pos.js"):
        urls = re.findall(r"wss://fstream\.binance\.com/[^\s\"'`]*", _read(p))
        assert urls, p
        assert all(u.startswith(("wss://fstream.binance.com/market/", "wss://fstream.binance.com/public/")) for u in urls), (p, urls)


def test_obsidian_day_summary_takes_a_start_day_report():
    rep = {"day": "2026-10-05", "parity": "시작한 날: 재계산 없음", "shadows": "없음", "data_quality": None,
           "fill_costs": [], "stop_slippage": "x", "strength": "x"}
    s = OS._day_summary("2026-10-05", 1, rep, 0)
    assert s["parity_accounts"] is None and s["bars"] is None and s["variants"] == {} and s["busts"] == []
