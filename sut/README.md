# `sut/` — W0.5 public generic CI (system-under-test lane)

This directory drives the **W0.5 public generic CI** for the `generic-arm64-engine`.
On each change, the `Generic ARM64 CI (W0.5)` workflow
(`.github/workflows/generic-ci.yml`) **rebuilds the pinned QEMU** from
signature-verified source and runs the **W0.3 generic-guest smoke test** plus the
**bounded W0.4 differential corpus** on a free GitHub-hosted `ubuntu-latest`
runner. TCG guest-ISA semantics are host-OS-independent, so this Linux lane
exercises the same emulated aarch64 behaviour as the pinned Windows build.

The **native ARM64 reference** (the differential oracle) is produced separately by
`.github/workflows/arm64-reference.yml` on a genuine `ubuntu-24.04-arm` runner and
committed to `reference/`. This lane diffs the SUT run against that pinned
reference — running **the same static aarch64 `corpus_runner` binary on both
sides**, the W0.4 fidelity property.

## Per-change lane (fast; gates changes)

1. **Rebuild QEMU 11.0.2** (`build_qemu.sh`): verify the release-manager signature,
   record and assert the source SHA-256, configure with **TCG + `virt` and every
   hardware accelerator compiled out**, build `qemu-system-aarch64`. Signature →
   hash → build order is enforced.
2. **Prove TCG / no KVM/WHPX**: `-accel help` lists `tcg` and neither `kvm` nor
   `whpx` (they are compiled out).
3. **Prepare pinned inputs** (`prepare_inputs.py`): decompress the UEFI firmware
   from the verified source tree (byte-identical to the W0.3 firmware) and
   download + verify the pinned Alpine aarch64 image (SHA-256 + published SHA-512).
4. **W0.3 smoke** (`smoke/`, `run_guest.sh`): boot the pinned Alpine guest under
   TCG, run the fixed command manifest, clean power-off → JUnit + boot transcript.
5. **Bounded W0.4 corpus** (`render_corpus_seed.py`, `extract_corpus.py`): run the
   shared static `corpus_runner` in-guest, collect (seeded), and diff against the
   native-ARM64 reference → **VALID** (good corpus passes **and** seeded mismatch
   rejected). A negative control proves the harness fails closed on an unseeded run.
6. **Retain logs + hashes** (`make_ci_manifest.py`): every transcript, result set,
   diff report, and the rebuilt-binary hash are uploaded as a retained artifact.

## Scheduled / soak lane (longer; not per-change)

The `soak` job runs on a daily `schedule` (or manual dispatch with `run_soak`),
repeating the bounded corpus differential for `SOAK_CYCLES` cycles. This is the
"longer conformance/soak" lane that cannot fit a per-change budget. **The full
72-hour per-host soak is Stage A WA.5 and is intentionally not run here.**

## Scope

Generic ARM64 only, neutral internal name `generic-arm64-engine`. This public CI
contains **only generic ARM64 artifacts** — no vendor-specific inputs,
configuration, secrets, or additional guest lanes. The full W0.4 architecture
matrix and the >10% median-regression dashboard are Stage A (WA.2, WA.6), out of
scope for W0.5. The CI artifact-leak test is W0.7.

## Files

| File | Role |
|---|---|
| `pins.json` | Pinned inputs: QEMU source (URL+SHA+signing key), firmware `.fd` hashes, Alpine image. |
| `build_qemu.sh` | Rebuild the pinned QEMU 11.0.2 (TCG + virt) from verified source. |
| `prepare_inputs.py` | Decompress/verify firmware; download/verify the guest image. |
| `run_guest.sh` | Boot the guest under TCG; emit run-result.json + serial transcript. |
| `emit_run_result.py` | Write the `gae-smoke/run-result@1` record consumed by the parser. |
| `render_corpus_seed.py` | NoCloud seed embedding the shared static `corpus_runner`. |
| `extract_corpus.py` | Pull the base64 corpus output from the transcript → raw lines. |
| `make_ci_manifest.py` | SHA-256 index of the retained artifacts. |
| `smoke/` | The W0.3 fixed command manifest + seed renderer + transcript parser (reused verbatim). |
