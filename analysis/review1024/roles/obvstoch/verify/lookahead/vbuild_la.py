"""Look-ahead verifier: rebuild the study's cache with its own oscore.build_coin into a separate /dev/shm folder
(so the study's rows can be compared row by row with an independent rebuild from the raw 1m bars)."""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import oscore as O
O.CACHE = "/dev/shm/claude_verify_la"
if __name__ == "__main__":
    from multiprocessing import get_context
    coins = sys.argv[1:] or list(O.COINS)
    allchk = {}
    with get_context("fork").Pool(2) as pool:
        for c, chk in pool.imap_unordered(O.build_coin, coins):
            allchk[c] = chk
    print(json.dumps(allchk, indent=1, default=float))
