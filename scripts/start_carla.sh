#!/usr/bin/env bash
# Start CARLA servers pinned to one GPU.
#   scripts/start_carla.sh <graphicsadapter> <port> [port...]
# -graphicsadapter selects the Vulkan physical device; verify with nvidia-smi
# after launch rather than assuming it matches the nvidia-smi index.
# Each server binds port, port+1 and port+2, so space ports at least 3 apart.
cd "$(dirname "$0")/.."
ROOT=$PWD
CARLA_ROOT=${CARLA_ROOT:-$ROOT/carla/CARLA_0.9.16}
LOG_DIR=${LOG_DIR:-$ROOT/logs}
mkdir -p "$LOG_DIR"
# env.sh appends to LD_LIBRARY_PATH, which is unset in a fresh shell; seed it
# before enabling `set -u` or sourcing aborts and CARLA never launches.
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
# Only present where the image lacks the Vulkan loader (scripts/setup_vulkan_userspace.sh)
GLVND_ENV=${GLVND_ENV:-$ROOT/vendor/glvnd/env.sh}
[ -f "$GLVND_ENV" ] && . "$GLVND_ENV"
set -u
ADAPTER=$1; shift
for PORT in "$@"; do
  setsid "$CARLA_ROOT/CarlaUE4.sh" -RenderOffScreen -nosound \
    -carla-rpc-port="$PORT" -graphicsadapter="$ADAPTER" \
    </dev/null > "$LOG_DIR/carla_${PORT}.log" 2>&1 &
  echo "  CARLA port $PORT on graphicsadapter $ADAPTER (pid $!)"
done
