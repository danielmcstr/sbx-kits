#!/usr/bin/env bash
set -u

SYNC_BIN="/usr/local/bin/agy-session"
WATCHER_PID=""
FINALIZED=0

cleanup() {
  if [ "$FINALIZED" -eq 1 ]; then
    return
  fi
  FINALIZED=1
  if [ -n "$WATCHER_PID" ] && kill -0 "$WATCHER_PID" 2>/dev/null; then
    kill "$WATCHER_PID" 2>/dev/null || true
    wait "$WATCHER_PID" 2>/dev/null || true
  fi
  "$SYNC_BIN" push --release-lock --quiet 2>/dev/null || true
}

trap cleanup EXIT

# 1. Hydrate persisted sessions from the mounted workspace before agy launches
"$SYNC_BIN" hydrate || true

# 2. Start background SQLite-safe periodic sync watcher (detached from TTY)
"$SYNC_BIN" watch --interval 20 </dev/null >/dev/null 2>&1 &
WATCHER_PID=$!

# 3. Build agy arguments; auto-continue only when configured and no args passed
ARGS=(--dangerously-skip-permissions)
if [ "$#" -eq 0 ] && "$SYNC_BIN" should-auto-resume >/dev/null 2>&1; then
  ARGS+=(--continue)
fi

# 4. Run agy directly in the foreground so it owns the controlling TTY natively
agy "${ARGS[@]}" "$@"
EXIT_CODE=$?

cleanup
exit "$EXIT_CODE"
