#!/bin/sh
# Daily copies of the paperbot databases (run by deploy/paperbot-backup.service), 14 days kept.
#
# Each copy is `VACUUM INTO` on a read-only connection (sqlite3 -readonly): one read transaction, a
# consistent snapshot that the live runner's commits (every 5 s) cannot restart. The sqlite3 `.backup`
# command used before copies 100 pages per step and starts over whenever another process commits
# between two steps, so on a large paper3.db it never finished and the databases after it were never
# copied. The small databases go first: agents3.db (the hypothesis ledger behind the gate's test count)
# and inbox.db (the owners' posts and approvals), then daily3.db and paper3.db. The backup writes none
# of them: a read-only connection never checkpoints a left-over WAL into the database file.
# A copy is written as <name>.db.part and renamed when complete, so a failed copy never looks whole;
# a second run on the same day keeps that day's good copy until the new one has replaced it (the
# rename is atomic). Parts left by a copy the unit's timeout killed are removed first.
# Exit status 1 when any copy failed (after the old copies are pruned), so the unit fails visibly.
lib=${PAPERBOT_LIB:-/var/lib/paperbot}
out=${PAPERBOT_BACKUPS:-/var/backups/paperbot}
d="$out/$(date -u +%Y%m%d)"
mkdir -p "$d" || exit 1
find "$out" -name '*.db.part' -type f -delete
fail=0
for f in agents3 inbox daily3 paper3; do
  src="$lib/$f.db"
  [ -f "$src" ] || continue
  rm -f "$d/$f.db.part"
  if printf "VACUUM INTO '%s';\n" "$d/$f.db.part" | sqlite3 -bail -readonly "$src" \
      && mv "$d/$f.db.part" "$d/$f.db"; then
    :
  else
    rm -f "$d/$f.db.part"
    echo "backup of $f.db failed" >&2
    fail=1
  fi
done
find "$out" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
exit $fail
