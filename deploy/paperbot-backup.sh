#!/bin/sh
# Daily copies of the paperbot databases (run by deploy/paperbot-backup.service), 14 days kept.
#
# Each copy is `VACUUM INTO` on a read-only connection (sqlite3 -readonly): one read transaction, a
# consistent snapshot that the live runner's commits (every 5 s) cannot restart. The sqlite3 `.backup`
# command used before copies 100 pages per step and starts over whenever another process commits
# between two steps, so on a large paper3.db it never finished and the databases after it were never
# copied. The small databases go first: agents3.db (the hypothesis ledger behind the gate's test count)
# and inbox.db (the owners' posts and approvals), liq.db (liquidations: no public history, a lost day is
# lost for good), the order executor's records (exec/executor.db for mainnet, exec/executor-testnet.db: its
# trades, fills, halts and open-position state; copied as executor.db / executor-testnet.db), the debate room's
# debate/debate.db (rounds, graded claims, the paid-API spend counter; group paperbot reads it), then daily3.db
# and paper3.db. The backup writes none
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
# keep this list the same as DB_NAMES in paperbot/offsite.py (tests/test_offsite.py checks it)
for f in agents3 inbox liq checkpoint exec/executor exec/executor-testnet shadow200/shadow200 debate/debate daily3 paper3; do
  src="$lib/$f.db"
  [ -f "$src" ] || continue
  n=$(basename "$f")
  rm -f "$d/$n.db.part"
  if printf "VACUUM INTO '%s';\n" "$d/$n.db.part" | sqlite3 -bail -readonly "$src" \
      && mv "$d/$n.db.part" "$d/$n.db"; then
    :
  else
    rm -f "$d/$n.db.part"
    echo "backup of $n.db failed" >&2
    fail=1
  fi
done
# The GH Coin call recorder's files (docs/ghcoin-recorder.md) are not a database: they go into one, ghcoin.db
# (table files: name, data), so the off-site copy sends them like the others. Restore: docs/ghcoin-recorder.md.
g="$lib/ghcoin"
if [ -f "$g/calls.jsonl" ] || [ -f "$g/patterns.jsonl" ] || [ -f "$g/state.json" ]; then
  rm -f "$d/ghcoin.db.part"
  if sqlite3 -bail "$d/ghcoin.db.part" "CREATE TABLE files (name TEXT PRIMARY KEY, data BLOB);
      INSERT INTO files VALUES ('calls.jsonl', readfile('$g/calls.jsonl')),
        ('patterns.jsonl', readfile('$g/patterns.jsonl')), ('state.json', readfile('$g/state.json'));
      DELETE FROM files WHERE data IS NULL;" && mv "$d/ghcoin.db.part" "$d/ghcoin.db"; then
    :
  else
    rm -f "$d/ghcoin.db.part"
    echo "backup of ghcoin.db failed" >&2
    fail=1
  fi
fi
find "$out" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
exit $fail
