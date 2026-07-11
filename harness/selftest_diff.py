#!/usr/bin/env python3
"""Tool-level self-test for the W0.4 diff engine (diff_corpus.py).

This validates the DIFF TOOL only. It synthesizes honest result sets from the
corpus manifest and proves three scenarios:

  1. good corpus passes        -- SUT == reference on every non-seed test, and the
                                  seed entry is mutated on the SUT side  => VALID
  2. seeded mismatch detected   -- (shown within scenario 1: the seed entry diverges
                                  and is flagged; a run whose seed is NOT mutated is
                                  rejected as SEED-NOT-DETECTED)          => INVALID
  3. real divergence fails      -- a non-seed test also diverges          => INVALID

IMPORTANT: this is NOT the W0.4 acceptance. The acceptance (plan §3 W0.4, DoD
#2/#3/#4) requires the SUT result set to come from a real run of the W0.2 pinned
qemu build and the reference result set to come from a real run on physical/cloud
ARM64 hardware. This self-test uses SYNTHETIC result sets to exercise the engine's
classification logic; it proves the oracle is *capable of failing*, which is a
prerequisite for trusting it, but it does not stand in for the hardware run.

Exit 0 iff every scenario behaves as expected; non-zero otherwise.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import diff_corpus  # noqa: E402

MANIFEST = os.path.join(HERE, "corpus-manifest.json")


def mutate(output):
    """Flip bit 0 of the leading 64-bit hex result, preserving any nzcv suffix."""
    parts = output.split(" ", 1)
    val = int(parts[0], 16) ^ 0x1
    head = "0x%016x" % val
    return head if len(parts) == 1 else head + " " + parts[1]


def build_sets(manifest_sha, manifest, *, mutate_seed, mutate_nonseed=None):
    ref_results = {}
    sut_results = {}
    for t in manifest["tests"]:
        tid = t["id"]
        expected = t["arch_expected"]
        ref_results[tid] = expected          # reference = pristine hardware truth
        sut = expected
        if t.get("seed_mismatch") is True and mutate_seed:
            sut = mutate(expected)            # SUT injects the seed mutation
        if mutate_nonseed and tid == mutate_nonseed:
            sut = mutate(expected)            # inject a real (non-seed) divergence
        sut_results[tid] = sut

    ref = {
        "schema": "gae-diff/results@1", "side": "reference",
        "corpus_manifest_version": manifest["version"],
        "corpus_manifest_sha256": manifest_sha,
        "seed_active": False,
        "engine": {"synthetic": True, "note": "self-test reference (NOT real hardware)"},
        "results": ref_results,
    }
    sut = {
        "schema": "gae-diff/results@1", "side": "sut",
        "corpus_manifest_version": manifest["version"],
        "corpus_manifest_sha256": manifest_sha,
        "seed_active": bool(mutate_seed),
        "engine": {"synthetic": True, "note": "self-test SUT (NOT real qemu run)"},
        "results": sut_results,
    }
    return sut, ref


def run_case(tmp, name, sut_obj, ref_obj):
    sp = os.path.join(tmp, f"{name}-sut.json")
    rp = os.path.join(tmp, f"{name}-ref.json")
    op = os.path.join(tmp, f"{name}-report.json")
    for p, o in ((sp, sut_obj), (rp, ref_obj)):
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(o, fh, indent=2)
    report = diff_corpus.diff(MANIFEST, sp, rp)
    with open(op, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2)
    return report


def main():
    manifest_sha = diff_corpus.sha256_file(MANIFEST)
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        # Scenario 1: good corpus + seed mutated on SUT -> VALID
        sut, ref = build_sets(manifest_sha, manifest, mutate_seed=True)
        r1 = run_case(tmp, "good", sut, ref)
        ok1 = (r1["harness_valid"] is True
               and r1["good_corpus_passes"] is True
               and r1["seed_detected"] is True
               and r1["counts"]["non_seed_divergences"] == 0
               and r1["counts"]["seed_detected"] == 1)
        print(f"[{'PASS' if ok1 else 'FAIL'}] scenario 1 good-corpus-passes + seed-detected "
              f"-> verdict={r1['verdict']}")
        failures += 0 if ok1 else 1

        # Scenario 2: seed NOT mutated (seed_active false) -> seed undetected -> INVALID
        sut, ref = build_sets(manifest_sha, manifest, mutate_seed=False)
        r2 = run_case(tmp, "noseed", sut, ref)
        ok2 = (r2["harness_valid"] is False
               and r2["good_corpus_passes"] is True
               and r2["seed_detected"] is False
               and r2["counts"]["seed_undetected"] == 1)
        print(f"[{'PASS' if ok2 else 'FAIL'}] scenario 2 seed-not-exercised rejected "
              f"-> verdict={r2['verdict']} (seed_detected={r2['seed_detected']})")
        failures += 0 if ok2 else 1

        # Scenario 3: seed mutated AND a real non-seed divergence -> INVALID
        victim = next(t["id"] for t in manifest["tests"] if not t.get("seed_mismatch"))
        sut, ref = build_sets(manifest_sha, manifest, mutate_seed=True, mutate_nonseed=victim)
        r3 = run_case(tmp, "divergence", sut, ref)
        ok3 = (r3["harness_valid"] is False
               and r3["good_corpus_passes"] is False
               and r3["seed_detected"] is True
               and r3["non_seed_divergences"] == [victim])
        print(f"[{'PASS' if ok3 else 'FAIL'}] scenario 3 real-divergence rejected "
              f"-> verdict={r3['verdict']} (divergences={r3['non_seed_divergences']})")
        failures += 0 if ok3 else 1

    print()
    if failures:
        print(f"SELF-TEST FAILED: {failures} scenario(s) did not behave as expected")
        return 1
    print("SELF-TEST PASSED: diff engine classifies good/seed/divergence correctly")
    print("NOTE: this validates the TOOL only; it is NOT the W0.4 hardware-referenced acceptance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
