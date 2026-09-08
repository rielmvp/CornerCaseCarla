#!/usr/bin/env bash
# Run the live demo and keep it running, on one GPU.
#
#   GPU=0 CARLA_PORT=2000 scripts/demo.sh      (settings from the environment)
#   scripts/stop_demo.sh            stops what this started
#
# Watches these services and starts ONLY the ones that are missing:
#   1. CARLA server       GPU $GPU, rpc port $CARLA_PORT
#   2. Alpamayo worker    the models in $MODELS resident, serving the job queue
#   3. page server        http://localhost:$DEMO_PORT/studio.html
#   4. cloudflared        only with TUNNEL=quick: an outbound quick tunnel, URL in
#                         outputs/logs/tunnel_url.txt (and in Cloudflare KV if set)
#
# It never kills anything: healthy processes are adopted, so re-running it during
# a demo interrupts nothing. Every lookup is scoped to this user and to an exact
# command string, so other users' processes are never matched.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
GPU=${GPU:-0}
CARLA_ADAPTER=${CARLA_ADAPTER:-$GPU}
CARLA_PORT=${CARLA_PORT:-2000}
CARLA_ROOT=${CARLA_ROOT:-carla/CARLA_0.9.16}
case "$CARLA_ROOT" in /*) ;; *) CARLA_ROOT=$ROOT/$CARLA_ROOT ;; esac
MODELS=${MODELS:-1,1.5}
DEMO_PORT=${DEMO_PORT:-8900}
PERIOD=${PERIOD:-15}
PY=$ROOT/.venv/bin/python
LOGS=$ROOT/outputs/logs
LIVE=$ROOT/outputs/live
mkdir -p "$LOGS" "$LIVE"

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
[ -f vendor/glvnd/env.sh ] && . vendor/glvnd/env.sh       # only where Vulkan needed the user-space fix
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}

if [ "${TUNNEL:-}" = quick ] && { [ -z "${DEMO_USER:-}" ] || [ -z "${DEMO_PASS:-}" ]; }; then
  echo "REFUSING to open a public tunnel without DEMO_USER and DEMO_PASS set."; exit 1
fi

log() { echo "[$(date -Is)] $*"; }

listening() {  # $1 = port
  "$PY" -c "
import socket,sys
s=socket.socket(); s.settimeout(1)
sys.exit(0 if s.connect_ex(('127.0.0.1',$1))==0 else 1)" 2>/dev/null
}

# first pid of MY process whose command contains the exact string $1
pid_of() { ps -u "$(id -u)" -o pid=,cmd= | grep -F -- "$1" | grep -v grep | awk '{print $1; exit}'; }

# Publish the tunnel hostname so the Worker in deploy/ can find it. Credentials
# come from the environment and are never echoed; only success or failure is logged.
publish_url() {
  [ -n "${CF_ACCOUNT_ID:-}" ] && [ -n "${CF_KV_TOKEN:-}" ] && [ -n "${CF_KV_NAMESPACE_ID:-}" ] || return 0
  ok=$(curl -s -m 20 -X PUT -H "Authorization: Bearer $CF_KV_TOKEN" \
    "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/storage/kv/namespaces/$CF_KV_NAMESPACE_ID/values/tunnel_url" \
    -F "value=$1" -F 'metadata={}' \
    | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('success'))" 2>/dev/null)
  [ "$ok" = True ] && log "published tunnel URL to Cloudflare KV" \
                   || log "WARNING: could not publish tunnel URL to Cloudflare KV"
}

start_carla() {
  log "CARLA :$CARLA_PORT is down - starting on graphics adapter $CARLA_ADAPTER"
  setsid "$CARLA_ROOT/CarlaUE4.sh" -RenderOffScreen -nosound \
    -carla-rpc-port="$CARLA_PORT" -graphicsadapter="$CARLA_ADAPTER" \
    </dev/null > "$LOGS/carla_$CARLA_PORT.log" 2>&1 &
  echo $! > "$LOGS/carla.pid"
  for _ in $(seq 1 60); do
    listening "$CARLA_PORT" && { log "CARLA :$CARLA_PORT up"; return 0; }
    sleep 2
  done
  log "CARLA :$CARLA_PORT did NOT come up - see $LOGS/carla_$CARLA_PORT.log"
  return 1
}

start_worker() {
  log "Alpamayo worker is down - starting (GPU $GPU, models $MODELS; loading takes a few minutes)"
  rm -f "$LIVE/worker_ready"
  CUDA_VISIBLE_DEVICES="$GPU" CARLA_PORT="$CARLA_PORT" MODELS="$MODELS" \
    setsid "$PY" "$ROOT/cornercase/live_worker.py" </dev/null >> "$LOGS/worker.log" 2>&1 &
  echo $! > "$LOGS/worker.pid"
}

start_server() {
  log "page server :$DEMO_PORT is down - starting (auth $([ -n "${DEMO_USER:-}" ] && echo on || echo off))"
  "$PY" "$ROOT/cornercase/build_studio.py" >> "$LOGS/server.log" 2>&1
  BIND_HOST=${BIND_HOST:-127.0.0.1} setsid "$PY" "$ROOT/cornercase/live_server.py" "$DEMO_PORT" \
    </dev/null >> "$LOGS/server.log" 2>&1 &
  echo $! > "$LOGS/server.pid"
}

start_tunnel() {
  log "cloudflared is down - starting a quick tunnel (the URL changes on every start)"
  : > "$LOGS/tunnel.log"
  setsid "${CLOUDFLARED:-cloudflared}" tunnel --url "http://localhost:$DEMO_PORT" \
    --no-autoupdate </dev/null >> "$LOGS/tunnel.log" 2>&1 &
  echo $! > "$LOGS/tunnel.pid"
  for _ in $(seq 1 30); do
    u=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOGS/tunnel.log" | head -1)
    if [ -n "$u" ]; then
      echo "$u" > "$LOGS/tunnel_url.txt"; log "public URL: $u/studio.html"
      publish_url "$u"; return 0
    fi
    sleep 2
  done
  log "cloudflared started but no URL appeared yet - see $LOGS/tunnel.log"
}

rm -f "$LOGS/.ready_announced"
log "demo starting - GPU $GPU, CARLA :$CARLA_PORT, models $MODELS, page :$DEMO_PORT"
echo "$$" > "$LOGS/demo.pid"
while true; do
  listening "$CARLA_PORT" || start_carla
  # the worker is useless without CARLA, so only start it once CARLA answers
  if listening "$CARLA_PORT" && [ -z "$(pid_of "$ROOT/cornercase/live_worker.py")" ]; then
    start_worker
  fi
  listening "$DEMO_PORT" || start_server
  if [ "${TUNNEL:-}" = quick ] && [ -z "$(pid_of 'tunnel --url http://localhost:'"$DEMO_PORT")" ]; then
    start_tunnel
  fi
  if [ -f "$LIVE/worker_ready" ] && [ ! -f "$LOGS/.ready_announced" ]; then
    log "READY - open http://localhost:$DEMO_PORT/studio.html"; touch "$LOGS/.ready_announced"
  fi
  sleep "$PERIOD"
done
