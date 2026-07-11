# ARMShift — generic ARM64 architecture differential harness

ARMShift runs a bounded, versioned corpus of **generic ARM64 (aarch64) architecture
tests** two ways and diffs the results:

- **SUT (system under test):** the corpus executed under a pinned `qemu-system-aarch64`
  build (an ARM64 guest under **TCG**). This side is run separately, off this repository.
- **Reference (the oracle):** the **same** corpus executed **natively on genuine ARM64
  silicon**. In this repository that reference is produced by the
  [`ARM64 reference`](.github/workflows/arm64-reference.yml) workflow on a GitHub-hosted
  `ubuntu-24.04-arm` standard runner.

The reference **must be independent of the emulator**: a run under the same translator it
is meant to check proves nothing about translation semantics. The reference job therefore
**fails closed** unless it is running on real aarch64 hardware (`uname -m = aarch64` and
`systemd-detect-virt` is not `qemu`/`tcg`). No third-party cloud (AWS/Azure/GCP) is
provisioned; the standard GitHub-hosted ARM64 runner is free on public repositories.

## The seeded mismatch (negative control)

A harness that has never been observed to fail has not been shown to be *capable* of
failing. Exactly one corpus entry (`seed_negctrl`) is a negative control. When the SUT
result set is collected in **seed mode** (`--side sut --seed`), `collect_results.py`
injects one documented, localized mutation — flip bit 0 of that entry's result — on the
**SUT side only**; the reference is never mutated. A correct harness then reports, in a
single diff report:

- every real (non-seed) test matches → **good corpus passes**, and
- the seed entry diverges → **seeded mismatch detected / rejected**.

If the seed is *not* flagged, the diff engine returns `INVALID` (exit 1): the oracle
cannot be trusted. `selftest_diff.py` proves all three behaviours (good corpus passes,
seed-not-detected is rejected, a real divergence is rejected) and runs in CI on ARM64.

## Oracle independence

`diff_corpus.py` decides the verdict **solely** by comparing the SUT run against the
reference run. It **never** consults the manifest's `arch_expected` field — that field
documents the architecturally-defined result for human review only. The truth is the
independent hardware run.

## Layout

| Path | Role |
|---|---|
| `harness/corpus-manifest.json` | Versioned (`v1`), reviewable corpus of deterministic ARM64 architecture tests (integer, mul, logical, shift, bitmanip, conditional, flags) plus one `seed_mismatch` negative control. |
| `harness/corpus_runner.c` | The corpus as portable aarch64 inline-asm; prints `<id>\t<canonical>` per test. Built as one **static** binary and run on **both** sides. |
| `harness/collect_results.py` | Wraps `corpus_runner` stdout into a `gae-diff/results@1` set bound to the exact manifest bytes; injects the seed mutation on `--side sut --seed`; refuses `--side reference --seed`. Fail-closed. |
| `harness/diff_corpus.py` | Diff engine. Consumes a SUT and a reference result set, verifies both bind to the exact manifest bytes, compares canonical outputs, emits `diff-report.json` + text. Fail-closed. |
| `harness/selftest_diff.py` | Tool-level self-test of the diff engine. Validates the tool, not a hardware run. |
| `.github/workflows/arm64-reference.yml` | Produces the native ARM64 reference bundle on `ubuntu-24.04-arm`. |

## Reference run (this repository, on ARM64 CI)

The workflow compiles the runner natively (static), verifies genuine silicon, runs the
corpus, and uploads `arm64-reference-bundle`:

- `results-reference.json` — the `gae-diff/results@1` reference set (never seeded),
- `corpus_runner` — the **static aarch64 binary** to reuse on the SUT side (same bytes),
- `runner-raw.reference.txt`, `provenance.txt`, `engine.json` — raw output and provenance.

## SUT run (separate) and the differential

On the host with the pinned `qemu-system-aarch64` (TCG) build, run the **same** static
binary inside the ARM64 guest, capture its stdout, then:

```sh
# SUT side (seed mode) -- qemu/TCG:
python3 harness/collect_results.py --manifest harness/corpus-manifest.json \
    --raw runner-raw.sut.txt --side sut --seed \
    --engine-json '{"accel":"tcg","engine":"qemu-system-aarch64 (pinned)"}' \
    --out results-sut.json

# Differential: download the reference bundle, then diff the two:
python3 harness/diff_corpus.py --manifest harness/corpus-manifest.json \
    --sut results-sut.json --reference results-reference.json \
    --out diff-report.json --text diff-report.txt
echo "exit=$?"   # 0 = VALID (good corpus passes AND seed rejected)
```

Exit codes: `0` harness valid (good corpus passed, seed rejected); `1` verdict failure (a
real divergence, or the seed was not detected); `2` structural error (fail-closed:
schema / manifest-binding / coverage problem).

## Result-set schema (`gae-diff/results@1`)

Both sides bind to the same `corpus_manifest_version` **and** `corpus_manifest_sha256`,
or the diff engine fails closed (exit 2):

```json
{
  "schema": "gae-diff/results@1",
  "side": "sut" | "reference",
  "corpus_manifest_version": 1,
  "corpus_manifest_sha256": "<sha256 of corpus-manifest.json bytes>",
  "seed_active": true,
  "engine": { "...": "provenance: qemu build + host, or ARM64 hardware profile" },
  "results": { "add_basic": "0x0000000000000003", "cmp_eq_flags": "0x0000000000000000 nzcv=0x6" }
}
```
