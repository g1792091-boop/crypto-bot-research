import sys
sys.dont_write_bytecode = True
import sys, time
sys.path.insert(0, "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze")
import analyze as A
sys.path.insert(0, "/home/user/crypto-bot-research")
run = A.Run(sys.argv[1], "current")
br, _ = A.make_brackets(None)
T = A.enrich_trades(run, 9, 0.0005)
S = A.replay_settings("quality_v1", 0.0005)
for flip in (False, True):
    R, info = A.replay_run(run, S, br, A.infer_specs(T), 1, flip=flip)
    print("flip", flip, {k: info[k] for k in ("signals", "replay_s", "s_per_1000_signals", "prep_s")})
