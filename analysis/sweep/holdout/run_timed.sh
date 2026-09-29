#!/bin/bash
# usage: run_timed.sh LOG cmd...   (records UTC start/end, wall seconds, exit code)
LOG=$1; shift
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export SWEEP_DATA=/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/holdout/data
s=$(date +%s); echo "START $(date -u +%FT%T) $*" > $LOG
"$@" >> $LOG 2>&1; rc=$?
e=$(date +%s); echo "END $(date -u +%FT%T) rc=$rc wall_s=$((e-s))" >> $LOG
