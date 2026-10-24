#!/usr/bin/env python3
"""Extract a server export zip (demo_export / ex_export) into a NEW empty folder, data files only.

    python3 extract_zip.py <export.zip> <new_empty_dir>

The zip is untrusted. Only plain data members (.json .npz .txt .db .csv .jsonl .md) with safe relative paths are
written; absolute paths, '..', links and any other file type are refused. Nothing from the zip is executed or
imported. Several zips that belong to one export (_1, _2) can go into one folder: pass them one after another with
--allow-nonempty on the second call (files that already exist are never overwritten).
"""
import os
import sys
import zipfile

ALLOWED = (".json", ".npz", ".txt", ".db", ".csv", ".jsonl", ".md")


def main(argv) -> int:
    allow = "--allow-nonempty" in argv
    argv = [a for a in argv if a != "--allow-nonempty"]
    if len(argv) != 2:
        print(__doc__)
        return 2
    zpath, out = argv
    if os.path.exists(out) and os.listdir(out) and not allow:
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
            if os.path.exists(dest):
                print(f"skipped (already there): {name!r}")
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
