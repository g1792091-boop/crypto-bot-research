#!/usr/bin/env python3
"""Extract a rule-bot export zip (analysis/live1019/rb_export.py) into a NEW empty folder, data only.

    python3 extract_zip.py <export.zip> <new_empty_dir>

The zip is untrusted: only plain .csv / .jsonl / .txt members with safe relative paths are written; anything else
(absolute paths, '..', links, other file types) is refused. Nothing from the zip is ever executed or imported.
"""
import os
import sys
import zipfile

ALLOWED = (".csv", ".jsonl", ".txt")


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    zpath, out = argv
    if os.path.exists(out) and os.listdir(out):
        print(f"refused: {out} exists and is not empty (use a new empty folder)")
        return 1
    os.makedirs(out, exist_ok=True)
    root = os.path.realpath(out)
    n = 0
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
        if bad:
            print(f"refused: CRC error in {bad}")
            return 1
        for info in z.infolist():
            name = info.filename
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if (name.startswith("/") or ".." in name.split("/") or "\\" in name or not name.endswith(ALLOWED)
                    or mode == 0o120000):
                print(f"skipped (not a plain data file): {name!r}")
                continue
            dest = os.path.realpath(os.path.join(root, name))
            if not dest.startswith(root + os.sep):
                print(f"skipped (outside folder): {name!r}")
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    dst.write(b)
            n += 1
    print(f"extracted {n} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
