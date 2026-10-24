"""Verifier (luck / multiple testing of OBV30@4h>SRSI_X@1h|a2): rebuild the obvstoch cache with the study's own
oscore.build_coin into a separate /dev/shm folder (does not touch the study's cache)."""
import os, sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
O.CACHE = "/dev/shm/claude_verify_srsix"
if __name__ == "__main__":
    from multiprocessing import get_context
    coins = sys.argv[1:] or list(O.COINS)
    allchk = {}
    with get_context("fork").Pool(2) as pool:
        for c, chk in pool.imap_unordered(O.build_coin, coins):
            allchk[c] = chk
    print(json.dumps(allchk, indent=1, default=float))
