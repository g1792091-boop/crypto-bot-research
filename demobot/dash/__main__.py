"""python -m demobot.dash [serve] [--snap DIR] [--host H] [--port 8090] [--data DIR]
python -m demobot.dash hash            # prints a DEMOBOT_DASH_PASSWORD_HASH for a password you type

Environment (/etc/demobot/demobot.env): DEMOBOT_DASH_PASSWORD_HASH, DEMOBOT_DASH_SECRET (32+ random characters),
DEMOBOT_SNAP (default /var/lib/demobot/snap), DEMOBOT_DASH_HOST (default 127.0.0.1), DEMOBOT_DASH_PORT (default 8090).
The dashboard refuses to start without a password hash and a secret."""

import argparse
import getpass
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.dash")
    ap.add_argument("cmd", nargs="?", default="serve", choices=["serve", "hash"])
    ap.add_argument("--snap", default=os.environ.get("DEMOBOT_SNAP", "/var/lib/demobot/snap"),
                    help="the engine's snapshot folder (read-only here)")
    ap.add_argument("--data", default=None, help="folder of past5y_<STRAT>_<tf>.npz (default demobot/data)")
    ap.add_argument("--host", default=os.environ.get("DEMOBOT_DASH_HOST") or "127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DEMOBOT_DASH_PORT") or 8090))
    args = ap.parse_args(argv)
    from .app import create_app, hash_password
    if args.cmd == "hash":
        pw = getpass.getpass("demo lab dashboard password: ")
        if len(pw) < 12:
            print("use at least 12 characters", file=sys.stderr)
            return 1
        if pw != getpass.getpass("again: "):
            print("passwords differ", file=sys.stderr)
            return 1
        print(hash_password(pw))
        return 0
    pw_hash = os.environ.get("DEMOBOT_DASH_PASSWORD_HASH", "").strip()
    secret = os.environ.get("DEMOBOT_DASH_SECRET", "").strip()
    if not pw_hash.startswith("pbkdf2$") or len(secret) < 32:
        print("set DEMOBOT_DASH_PASSWORD_HASH (python -m demobot.dash hash) and DEMOBOT_DASH_SECRET (32+ random chars)",
              file=sys.stderr)
        return 1
    import uvicorn
    app = create_app(args.snap, pw_hash, secret.encode(), data_dir=args.data)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=False, server_header=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
