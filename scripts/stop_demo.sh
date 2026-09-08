#!/usr/bin/env bash
# Stop what scripts/demo.sh started, by the PIDs it recorded - nothing else.
cd "$(dirname "$0")/.." || exit 1
LOGS=outputs/logs
for name in demo tunnel server worker carla; do
  f=$LOGS/$name.pid
  [ -f "$f" ] || continue
  pid=$(cat "$f")
  if kill -0 "$pid" 2>/dev/null; then
    # CARLA and the worker were started with setsid: stop their whole group
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    echo "stopped $name (pid $pid)"
  fi
  rm -f "$f"
done
rm -f "$LOGS/.ready_announced" outputs/live/worker_ready
