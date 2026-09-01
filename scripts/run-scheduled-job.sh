#!/bin/bash
# run-scheduled-job.sh — wrapper invoked by launchd for each scheduled job.
#
# This file is DEPLOYED to ~/Library/Application Support/research-bot/scripts/
# by schedule-sync.py. The deployed copy is what launchd invokes (TCC-unprotected
# location, no Documents-folder permission needed). The source-of-truth is the
# version in the repo's scripts/ — edit there, re-run schedule-sync.py to deploy.
#
# Arguments:
#   $1  job-id          (e.g. "weekly-intelligence-digest")
#   $2  mode            (queue | claude-headless)
#   $3  skill           (the skill name to invoke, usually = job-id)
#   $4  timeout-secs    (max seconds; only applied to claude-headless mode)
#   $5  every_n_weeks   (optional, default 1; wrapper checks week parity if >1)
#   $6  category        (optional, default ""; names the slice of the skill to run,
#                        e.g. "voices-security". Empty for uncategorized jobs.)

set -euo pipefail

if [ $# -lt 4 ]; then
    echo "usage: $0 <job-id> <mode> <skill> <timeout-secs> [every_n_weeks] [category]" >&2
    exit 64
fi

JOB_ID="$1"
MODE="$2"
SKILL="$3"
TIMEOUT="$4"
EVERY_N_WEEKS="${5:-1}"
CATEGORY="${6:-}"

# All operational paths live in TCC-unprotected locations.
# LOG_DIR / QUEUE_DIR come from the plist's EnvironmentVariables (baked in by
# schedule-sync.py from scheduled-jobs.yml). The fallbacks keep manual
# invocation working when the vars aren't set.
BASE_DIR="$HOME/Library/Application Support/research-bot"
STATE_DIR="$BASE_DIR/state"
LOG_DIR="${RESEARCH_BOT_LOG_DIR:-$HOME/Library/Logs/research-bot}"
QUEUE_DIR="${RESEARCH_BOT_QUEUE_DIR:-$HOME/Obsidian/Research-Brain/_inbox/scheduled-jobs}"

mkdir -p "$STATE_DIR" "$LOG_DIR" "$QUEUE_DIR"

LOG_FILE="$LOG_DIR/$JOB_ID.log"
START_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TODAY="$(date +%Y-%m-%d)"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG_FILE"
}

log "===== Starting $JOB_ID (mode=$MODE, skill=$SKILL, timeout=${TIMEOUT}s, category=${CATEGORY:-none}) ====="

# What the skill is asked to do, with or without a category slice.
if [ -n "$CATEGORY" ]; then
    RUN_INSTRUCTION="Run the $SKILL skill for the $CATEGORY category"
else
    RUN_INSTRUCTION="Run the $SKILL skill"
fi

# Biweekly check
if [ "$EVERY_N_WEEKS" -gt 1 ]; then
    EPOCH_NOW=$(date +%s)
    EPOCH_REF=$(date -j -f "%Y-%m-%d" "2024-01-01" "+%s")
    DAYS_SINCE=$(( (EPOCH_NOW - EPOCH_REF) / 86400 ))
    WEEKS_SINCE=$(( DAYS_SINCE / 7 ))
    REMAINDER=$(( WEEKS_SINCE % EVERY_N_WEEKS ))
    if [ "$REMAINDER" -ne 0 ]; then
        log "  skip: week-parity check (week=$WEEKS_SINCE, every_n=$EVERY_N_WEEKS, remainder=$REMAINDER)"
        echo "$START_TS" > "$STATE_DIR/$JOB_ID.last-check"
        exit 0
    fi
fi

EXIT_CODE=0

case "$MODE" in
    queue)
        MARKER="$QUEUE_DIR/${TODAY}-${JOB_ID}.md"
        if [ -e "$MARKER" ]; then
            log "  marker already exists (idempotent): $MARKER"
        else
            cat > "$MARKER" <<EOF
---
title: "Scheduled job due: $SKILL"
created: $TODAY
updated: $TODAY
tags: [scheduled, scheduled-job-marker, $JOB_ID]
source_skill: schedule-runner
confidence: 3
job_id: $JOB_ID
skill: $SKILL
category: $CATEGORY
queued_at: $START_TS
status: queued
---

# Scheduled job due: $SKILL

The \`$SKILL\` scheduled agent is due. Run it interactively via Claude Code:

> $RUN_INSTRUCTION

When done, delete this marker (\`$MARKER\`).
EOF
            log "  queued marker: $MARKER"
        fi
        EXIT_CODE=0
        ;;
    claude-headless)
        ENV_FILE="$HOME/.config/research-bot/env"
        if [ -f "$ENV_FILE" ]; then
            # shellcheck disable=SC1090
            set -a; source "$ENV_FILE"; set +a
            log "  sourced env from $ENV_FILE"
        else
            log "  WARNING: no env file at $ENV_FILE; ANTHROPIC_API_KEY may not be set"
        fi
        export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

        CLAUDE_BIN="$(command -v claude || true)"
        if [ -z "$CLAUDE_BIN" ]; then
            log "  ERROR: 'claude' binary not found on PATH"
            EXIT_CODE=127
        else
            PROMPT="$RUN_INSTRUCTION now."
            log "  invoking: $CLAUDE_BIN -p \"$PROMPT\""
            TIMEOUT_BIN="$(command -v gtimeout || command -v timeout || true)"
            if [ -n "$TIMEOUT_BIN" ]; then
                "$TIMEOUT_BIN" "$TIMEOUT" "$CLAUDE_BIN" -p "$PROMPT" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?
            else
                "$CLAUDE_BIN" -p "$PROMPT" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?
            fi
            log "  claude exit code: $EXIT_CODE"
        fi
        ;;
    *)
        log "  ERROR: unknown mode '$MODE' — expected queue|claude-headless"
        EXIT_CODE=64
        ;;
esac

END_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "===== Finished $JOB_ID (exit=$EXIT_CODE, end=$END_TS) ====="

echo "$END_TS" > "$STATE_DIR/$JOB_ID.last-run"
echo "$EXIT_CODE" > "$STATE_DIR/$JOB_ID.last-exit-code"

exit "$EXIT_CODE"
