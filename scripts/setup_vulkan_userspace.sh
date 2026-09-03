#!/usr/bin/env bash
# User-space Vulkan for containers whose image is missing the loader.
#   scripts/setup_vulkan_userspace.sh        -> vendor/glvnd/{debs,root,env.sh}
#
# Symptom: CUDA works, but CARLA never opens its RPC port and vulkaninfo fails.
# Cause: the image installs NVIDIA's EGL/GLES *vendor* libraries but not libglvnd's
# dispatch libraries (libEGL.so.1, libGLESv2.so.2) or the Vulkan loader
# (libvulkan.so.1). NVIDIA's Vulkan ICD dlopens libEGL.so.1 during init; without it
# vk_icdNegotiateLoaderICDInterfaceVersion returns -3 (VK_ERROR_INITIALIZATION_FAILED)
# before touching any device. `strace -f -e openat` on vulkaninfo shows the ENOENT.
#
# No root: packages are fetched with `apt-get download` and unpacked with
# `dpkg-deb -x`. Nothing outside vendor/glvnd is modified. Use the distro's own
# versions - libvulkan1 from a newer release needs a newer glibc than the host has.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=$PWD/vendor/glvnd
mkdir -p "$DEST/debs" "$DEST/root"
(cd "$DEST/debs" && apt-get download libegl1 libgles2 libglvnd0 libvulkan1 vulkan-tools)
for d in "$DEST"/debs/*.deb; do dpkg-deb -x "$d" "$DEST/root"; done

cat > "$DEST/env.sh" <<EOF
# Source this to get GPU Vulkan from the user-space libraries in vendor/glvnd.
export LD_LIBRARY_PATH="$DEST/root/usr/lib/x86_64-linux-gnu:\$LD_LIBRARY_PATH"
export VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json
export PATH="$DEST/root/usr/bin:\$PATH"
EOF
echo "wrote $DEST/env.sh - check with: . $DEST/env.sh && vulkaninfo --summary"
