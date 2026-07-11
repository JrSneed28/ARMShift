#!/usr/bin/env bash
# =============================================================================
# W0.5 public-CI SUT lane -- rebuild the pinned QEMU 11.0.2 from verified source
# (generic-arm64-engine). Linux (ubuntu-latest) port of the W0.2 build driver.
#
# Order is non-negotiable (plan section 3 W0.2; W0.2 "Notes and constraints"):
#   signature verification  ->  SHA-256 recording  ->  build.
# A hash recorded from an unverified download is not baseline evidence.
#
# In order this script:
#   1. downloads qemu-11.0.2.tar.xz + .sig (cache-aware),
#   2. imports the QEMU release-manager key and ASSERTS the imported primary
#      fingerprint equals the trust anchor published at qemu.org/download,
#   3. verifies the detached signature (requires GOODSIG + VALIDSIG),
#   4. records the tarball SHA-256 and asserts it equals the pinned value,
#   5. extracts the source and asserts the aarch64-softmmu tree is complete,
#   6. configures with TCG + `virt` and EVERY hardware accelerator compiled OUT,
#      then builds qemu-system-aarch64 (no `.exe`; this is a native ELF).
#
# Scope: common generic ARM64 work, neutral name generic-arm64-engine. Only
# generic ARM64 source is fetched, extracted, or recorded -- no vendor-specific
# artifact. Uses only free GitHub-hosted compute; no third-party cloud, no secrets.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PINS="$HERE/pins.json"

# Read pins with python3 (always present on ubuntu-latest).
read_pin() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))$2)" "$PINS"; }

QEMU_VERSION="$(read_pin "$PINS" "['qemu']['version']")"
QEMU_KEY_FPR="$(read_pin "$PINS" "['qemu']['release_key_fpr']")"
SRC_URL="$(read_pin "$PINS" "['qemu']['source_url']")"
SIG_URL="$(read_pin "$PINS" "['qemu']['source_sig_url']")"
PINNED_SRC_SHA="$(read_pin "$PINS" "['qemu']['source_sha256']")"

BUILD_ROOT="${BUILD_ROOT:-$PWD/.w05/qemu}"
DL_DIR="$BUILD_ROOT/dl"
SRC_DIR="$BUILD_ROOT/src"
BUILD_DIR="$BUILD_ROOT/build"
LOG_DIR="$BUILD_ROOT/logs"
GNUPGHOME_DIR="$BUILD_ROOT/gnupg"
mkdir -p "$DL_DIR" "$SRC_DIR" "$BUILD_DIR" "$LOG_DIR"

TARBALL="qemu-$QEMU_VERSION.tar.xz"
SIG="$TARBALL.sig"
KEY_URLS=(
  "https://keyserver.ubuntu.com/pks/lookup?op=get&options=mr&search=0x$QEMU_KEY_FPR"
  "https://keys.openpgp.org/vks/v1/by-fingerprint/$QEMU_KEY_FPR"
)

fetch_cached() {  # url dest
  local url="$1" dest="$2"
  if [[ -s "$dest" ]]; then echo "    cached: $(basename "$dest")"; return 0; fi
  echo "    download: $(basename "$dest")"
  curl -fsSL --retry 3 --max-time 1200 -o "$dest" "$url"
}

echo "==> 1. Download source + signature"
fetch_cached "$SRC_URL" "$DL_DIR/$TARBALL"
fetch_cached "$SIG_URL" "$DL_DIR/$SIG"

echo "==> 2. Import release key and assert fingerprint == trust anchor"
export GNUPGHOME="$GNUPGHOME_DIR"
rm -rf "$GNUPGHOME"; mkdir -p "$GNUPGHOME"; chmod 700 "$GNUPGHOME"
imported=0
for kurl in "${KEY_URLS[@]}"; do
  if curl -fsSL --max-time 90 -o "$DL_DIR/qemu-release-key.asc" "$kurl" \
     && gpg --batch --import "$DL_DIR/qemu-release-key.asc" 2>&1; then
    imported=1; break
  fi
  echo "    keysource failed, trying next: $kurl" >&2
done
[[ "$imported" == 1 ]] || { echo "FAILED: could not import the release key." >&2; exit 1; }

got_fpr="$(gpg --batch --with-colons --fingerprint "$QEMU_KEY_FPR" \
           | awk -F: '/^fpr:/ {print $10; exit}')"
if [[ "$got_fpr" != "$QEMU_KEY_FPR" ]]; then
  echo "FAILED: imported fingerprint '$got_fpr' != trust anchor '$QEMU_KEY_FPR'." >&2
  exit 1
fi
echo "    fingerprint matches qemu.org trust anchor: $got_fpr"

echo "==> 3. Verify detached signature (require GOODSIG + VALIDSIG)"
status="$(gpg --status-fd 1 --verify "$DL_DIR/$SIG" "$DL_DIR/$TARBALL" 2>/dev/null)"
echo "$status" | sed 's/^/    /'
if echo "$status" | grep -q 'BADSIG\|ERRSIG\|NO_PUBKEY\|EXPSIG'; then
  echo "FAILED: signature did not verify." >&2; exit 1
fi
echo "$status" | grep -q "GOODSIG"                || { echo "FAILED: no GOODSIG." >&2; exit 1; }
echo "$status" | grep -q "VALIDSIG $QEMU_KEY_FPR" || { echo "FAILED: no VALIDSIG for the trust anchor." >&2; exit 1; }
echo "    signature: GOOD, VALIDSIG for $QEMU_KEY_FPR"

echo "==> 4. Record tarball SHA-256 (post-verification) and assert == pin"
SHA256="$(sha256sum "$DL_DIR/$TARBALL" | cut -d' ' -f1)"
echo "    $SHA256  $TARBALL"
if [[ "$SHA256" != "$PINNED_SRC_SHA" ]]; then
  echo "FAILED: tarball SHA-256 '$SHA256' != pinned '$PINNED_SRC_SHA'." >&2
  exit 1
fi
echo "    matches pinned source SHA-256"

echo "==> 5. Extract source and assert the aarch64-softmmu tree is complete"
TREE="$SRC_DIR/qemu-$QEMU_VERSION"
if [[ ! -x "$TREE/configure" ]]; then
  rm -rf "$TREE"
  tar -C "$SRC_DIR" -xf "$DL_DIR/$TARBALL"
fi
[[ "$(cat "$TREE/VERSION")" == "$QEMU_VERSION" ]] || { echo "FAILED: VERSION mismatch." >&2; exit 1; }
for f in configure meson.build hw/arm/virt.c target/arm/meson.build accel/tcg/meson.build \
         pc-bios/edk2-aarch64-code.fd.bz2 pc-bios/edk2-arm-vars.fd.bz2; do
  [[ -e "$TREE/$f" ]] || { echo "FAILED: essential build input missing: $f" >&2; exit 1; }
done
echo "    essential aarch64-softmmu build tree present"

echo "==> 6. Configure (TCG + virt; every hardware accelerator compiled OUT) and build"
# Byte-for-byte the same accelerator/target posture as the W0.2 build driver.
CONFIGURE_ARGS=(
  --target-list=aarch64-softmmu
  --enable-tcg
  --disable-kvm
  --disable-whpx
  --disable-mshv
  --disable-hvf
  --disable-nvmm
  --disable-nitro
  --disable-xen
  --enable-slirp
  --disable-docs
  --disable-werror
)
cd "$BUILD_DIR"
if command -v ccache >/dev/null 2>&1; then
  export CC="ccache cc"
  echo "    ccache enabled: $(ccache --version | head -1)"
fi
echo "    configure ${CONFIGURE_ARGS[*]}"
"$TREE/configure" "${CONFIGURE_ARGS[@]}" 2>&1 | tee "$LOG_DIR/configure.log"
if [[ -f "$BUILD_DIR/meson-logs/meson-log.txt" ]]; then
  cp -f "$BUILD_DIR/meson-logs/meson-log.txt" "$LOG_DIR/meson-log.txt"
fi

NPROC="$(nproc 2>/dev/null || echo 4)"
echo "==> Building qemu-system-aarch64 (ninja -j$NPROC)"
ninja -C "$BUILD_DIR" -j"$NPROC" qemu-system-aarch64 2>&1 | tee "$LOG_DIR/build.log"

BIN="$BUILD_DIR/qemu-system-aarch64"
[[ -x "$BIN" ]] || { echo "BUILD FAILED: $BIN absent after ninja." >&2; exit 1; }

BIN_SHA="$(sha256sum "$BIN" | cut -d' ' -f1)"
BIN_BYTES="$(stat -c %s "$BIN")"
echo "==> Build complete"
echo "    binary : $BIN"
echo "    size   : $BIN_BYTES bytes"
echo "    sha256 : $BIN_SHA"

# Emit a machine-readable build manifest (source hash + per-run binary hash).
python3 - "$PINS" "$SHA256" "$BIN" "$BIN_SHA" "$BIN_BYTES" > "$LOG_DIR/build-manifest.json" <<'PY'
import json, sys
pins = json.load(open(sys.argv[1]))
print(json.dumps({
    "schema": "gae-ci/build-manifest@1",
    "work_item": "W0.5",
    "engine_internal_name": "generic-arm64-engine",
    "qemu_version": pins["qemu"]["version"],
    "source_tarball": pins["qemu"]["source_tarball"],
    "source_sha256": sys.argv[2],
    "source_sha256_pinned": pins["qemu"]["source_sha256"],
    "signature": "GOOD; VALIDSIG " + pins["qemu"]["release_key_fpr"],
    "configure_args": [
        "--target-list=aarch64-softmmu","--enable-tcg","--disable-kvm","--disable-whpx",
        "--disable-mshv","--disable-hvf","--disable-nvmm","--disable-nitro","--disable-xen",
        "--enable-slirp","--disable-docs","--disable-werror"
    ],
    "binary_path": sys.argv[3],
    "binary_sha256": sys.argv[4],
    "binary_bytes": int(sys.argv[5]),
    "binary_hash_note": "rebuilt from source on a Linux hosted runner; the hash is recorded per run, not pinned (a native Linux build differs from the W0.2 Windows/MSYS2 binary; both are the pinned 11.0.2 source with the identical TCG+virt, accelerators-out configuration)."
}, indent=2))
PY
echo "    build manifest: $LOG_DIR/build-manifest.json"

# Export paths for later workflow steps.
if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    echo "QEMU_BIN=$BIN"
    echo "QEMU_SRC_TREE=$TREE"
    echo "QEMU_BUILD_LOGDIR=$LOG_DIR"
    echo "QEMU_BIN_SHA=$BIN_SHA"
  } >> "$GITHUB_ENV"
fi
