#!/usr/bin/env bash
# Download and unpack the CARLA 0.9.16 server (~8.3 GB download, ~19 GB unpacked).
#   scripts/get_carla.sh                   -> carla/CARLA_0.9.16  (or $CARLA_ROOT)
# 0.9.16 is the only version still on an official mirror (docs/carla_setup.md).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
DEST=${CARLA_ROOT:-carla/CARLA_0.9.16}
URL=https://downloads.carlasim.com/Linux/CARLA_0.9.16.tar.gz
if [ -x "$DEST/CarlaUE4.sh" ]; then echo "CARLA already in $DEST"; exit 0; fi
mkdir -p "$DEST"
curl -fL --retry 3 "$URL" | tar -xz -C "$DEST"
echo "CARLA 0.9.16 in $DEST ($(cat "$DEST/VERSION" 2>/dev/null))"
