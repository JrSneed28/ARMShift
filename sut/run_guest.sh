#!/usr/bin/env bash
# =============================================================================
# W0.5 public-CI SUT lane -- boot the pinned generic ARM64 guest under TCG.
# Linux port of the W0.3 run_smoke.ps1 QEMU invocation. Used for BOTH boots:
#   * the W0.3 smoke boot (fixed command manifest), and
#   * the W0.4 corpus boot (runs the shared static aarch64 corpus_runner).
#
# TCG only: -accel tcg, no KVM. The guest powers off on the guest-initiated
# PSCI SYSTEM_OFF; a hard timeout bounds a hung boot. Emits <out>/run-result.json
# (gae-smoke/run-result@1) which parse_transcript.py consumes, plus the raw
# serial transcript. TCG guest-ISA semantics are host-OS-independent, so this
# Linux boot exercises the same emulated aarch64 behaviour as the W0.3 Windows run.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QEMU=""; IMAGE=""; SEED=""; CODE_FD=""; VARS_FD=""; OUTDIR=""
CPU="cortex-a72"; SMP="2"; MEM="2048"; TIMEOUT="900"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --qemu) QEMU="$2"; shift 2;;
    --image) IMAGE="$2"; shift 2;;
    --seed) SEED="$2"; shift 2;;
    --code-fd) CODE_FD="$2"; shift 2;;
    --vars-fd) VARS_FD="$2"; shift 2;;
    --out) OUTDIR="$2"; shift 2;;
    --cpu) CPU="$2"; shift 2;;
    --smp) SMP="$2"; shift 2;;
    --mem) MEM="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
for p in "$QEMU" "$IMAGE" "$SEED" "$CODE_FD" "$VARS_FD" "$OUTDIR"; do
  [[ -n "$p" ]] || { echo "missing required argument" >&2; exit 2; }
done
for f in "$QEMU" "$IMAGE" "$SEED" "$CODE_FD" "$VARS_FD"; do
  [[ -e "$f" ]] || { echo "required input not found: $f" >&2; exit 2; }
done
mkdir -p "$OUTDIR"

TRANSCRIPT="$OUTDIR/boot-transcript.log"
QERR="$OUTDIR/qemu-stderr.log"
VARS_RUN="$OUTDIR/edk2-arm-vars-run.fd"   # writable per-run UEFI vars copy
RESULT="$OUTDIR/run-result.json"
rm -f "$TRANSCRIPT" "$QERR" "$VARS_RUN" "$RESULT"
cp -f "$VARS_FD" "$VARS_RUN"

QARGS=(
  -machine virt
  -accel tcg
  -cpu "$CPU"
  -smp "$SMP"
  -m "$MEM"
  -drive "if=pflash,format=raw,unit=0,readonly=on,file=$CODE_FD"
  -drive "if=pflash,format=raw,unit=1,file=$VARS_RUN"
  -drive "if=virtio,format=qcow2,file=$IMAGE,snapshot=on"
  -drive "if=virtio,format=raw,file=$SEED,readonly=on"
  -display none
  -chardev "file,id=cons0,path=$TRANSCRIPT"
  -serial chardev:cons0
  -no-reboot
)

echo "Launching QEMU under TCG (timeout ${TIMEOUT}s)..."
QEMU_SHA="$(sha256sum "$QEMU" | cut -d' ' -f1)"
START_EPOCH="$(date -u +%s)"
START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

set +e
timeout --signal=KILL "${TIMEOUT}" "$QEMU" "${QARGS[@]}" 2>"$QERR"
EXIT_CODE=$?
set -e

END_EPOCH="$(date -u +%s)"
END_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ELAPSED=$(( END_EPOCH - START_EPOCH ))
TIMED_OUT=false
# `timeout --signal=KILL` returns 137 (128+9) when it kills the child.
if [[ "$EXIT_CODE" -eq 137 ]]; then TIMED_OUT=true; fi

TRANSCRIPT_SHA=""
[[ -f "$TRANSCRIPT" ]] && TRANSCRIPT_SHA="$(sha256sum "$TRANSCRIPT" | cut -d' ' -f1)"

# Emit run-result.json (gae-smoke/run-result@1) consumed by parse_transcript.py.
# All values are passed as argv (no source interpolation) for robustness.
python3 "$HERE/emit_run_result.py" \
  --out "$RESULT" --qemu "$QEMU" --qemu-sha "$QEMU_SHA" \
  --cpu "$CPU" --smp "$SMP" --mem "$MEM" \
  --code-fd "$CODE_FD" --vars-fd "$VARS_FD" --image "$IMAGE" --seed "$SEED" \
  --started "$START_ISO" --ended "$END_ISO" --elapsed "$ELAPSED" \
  --timeout "$TIMEOUT" --timed-out "$TIMED_OUT" --exit-code "$EXIT_CODE" \
  --transcript "$TRANSCRIPT" --transcript-sha "$TRANSCRIPT_SHA" --qerr "$QERR"

echo "QEMU exit=$EXIT_CODE elapsed=${ELAPSED}s timed_out=$TIMED_OUT"
echo "transcript: $TRANSCRIPT ($( [[ -f "$TRANSCRIPT" ]] && stat -c %s "$TRANSCRIPT" || echo 0 ) bytes)"
echo "run-result: $RESULT"
if [[ "$TIMED_OUT" == true || "$EXIT_CODE" -ne 0 ]]; then exit 1; else exit 0; fi
