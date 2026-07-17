#!/usr/bin/env python3
"""W0.4 independent differential harness -- diff engine.

Consumes two result sets for the SAME versioned corpus manifest:

  * --sut        the system-under-test: the W0.2 pinned qemu-system-aarch64 build
                 (ARM64 guest under TCG on the Windows host).
  * --reference  the semantic reference: the SAME corpus executed on physical or
                 cloud ARM64 hardware. This RUN is the oracle (plan §3 W0.4, DoD #4).

It diffs the two canonical result maps and emits a machine-readable diff report
plus a human-readable summary.

Oracle independence (important):
  The diff engine decides the verdict SOLELY by comparing the SUT run against the
  reference run. It never consults the manifest's 'arch_expected' field -- that
  field is a human-review convenience only. Comparing a translator against its own
  architectural definition proves nothing about translation semantics; the truth
  is the independent hardware run.

Verdict (a single report satisfies plan §3 W0.4's "good corpus passes AND seeded
mismatch fails"):
  good_corpus_passes = every non-seed test's SUT output equals its reference output
  seed_detected      = every seed_mismatch negative-control test differs between
                       SUT and reference
  harness_valid      = good_corpus_passes AND seed_detected

Exit codes:
  0  harness_valid (good corpus passed and the seeded mismatch was rejected)
  1  verdict failure (a real divergence, or the seed was NOT detected)
  2  structural error (fail-closed: schema/manifest-binding/coverage problem)
"""
import argparse
import hashlib
import json
import sys


SCHEMA_RESULTS = "gae-diff/results@1"
SCHEMA_REPORT = "gae-diff/diff-report@1"


class StructuralError(Exception):
    """A fail-closed error: inputs are not a well-formed, manifest-bound pair."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_manifest(path):
    m = load_json(path)
    if m.get("schema") != "gae-diff/corpus-manifest@1":
        raise StructuralError(f"manifest {path}: unexpected schema {m.get('schema')!r}")
    tests = m.get("tests")
    if not isinstance(tests, list) or not tests:
        raise StructuralError(f"manifest {path}: no tests")
    ids = []
    seed_ids = []
    for t in tests:
        tid = t.get("id")
        if not tid:
            raise StructuralError(f"manifest {path}: a test has no id")
        if tid in ids:
            raise StructuralError(f"manifest {path}: duplicate test id {tid!r}")
        ids.append(tid)
        if t.get("seed_mismatch") is True:
            seed_ids.append(tid)
    if not seed_ids:
        raise StructuralError(
            f"manifest {path}: no seed_mismatch negative control -- a harness that "
            f"cannot be shown to fail is not a valid oracle (plan §3 W0.4)"
        )
    return m, ids, seed_ids


def load_results(path, expected_side, manifest_version, manifest_sha):
    r = load_json(path)
    if r.get("schema") != SCHEMA_RESULTS:
        raise StructuralError(f"{path}: unexpected schema {r.get('schema')!r}")
    if r.get("side") != expected_side:
        raise StructuralError(
            f"{path}: side is {r.get('side')!r}, expected {expected_side!r}"
        )
    if r.get("corpus_manifest_version") != manifest_version:
        raise StructuralError(
            f"{path}: corpus_manifest_version {r.get('corpus_manifest_version')!r} "
            f"!= manifest version {manifest_version!r}"
        )
    if r.get("corpus_manifest_sha256") != manifest_sha:
        raise StructuralError(
            f"{path}: corpus_manifest_sha256 does not match the manifest bytes "
            f"({r.get('corpus_manifest_sha256')!r} != {manifest_sha!r}); the result "
            f"set is not bound to this exact reviewed corpus"
        )
    results = r.get("results")
    if not isinstance(results, dict):
        raise StructuralError(f"{path}: 'results' must be an object of id -> output")
    return r, results


def diff(manifest_path, sut_path, ref_path):
    manifest_sha = sha256_file(manifest_path)
    manifest, ids, seed_ids = load_manifest(manifest_path)
    version = manifest.get("version")

    sut, sut_results = load_results(sut_path, "sut", version, manifest_sha)
    ref, ref_results = load_results(ref_path, "reference", version, manifest_sha)

    # The reference is an untouched hardware run. It must never carry the seed mutation.
    if ref.get("seed_active") is True:
        raise StructuralError(
            f"{ref_path}: reference seed_active=true -- the reference hardware run "
            f"must never be mutated; the seed is injected only on the SUT side"
        )

    # Fail-closed coverage: every manifest id present on both sides, no extras.
    for side_name, res in (("sut", sut_results), ("reference", ref_results)):
        missing = [i for i in ids if i not in res]
        extra = [i for i in res if i not in ids]
        if missing:
            raise StructuralError(f"{side_name} missing results for: {missing}")
        if extra:
            raise StructuralError(f"{side_name} has results for unknown ids: {extra}")

    per_test = []
    nonseed_mismatch = []
    seed_undetected = []
    seed_detected_ids = []
    for tid in ids:
        is_seed = tid in seed_ids
        s = sut_results[tid]
        rr = ref_results[tid]
        match = (s == rr)
        if is_seed:
            status = "seed-detected" if not match else "SEED-NOT-DETECTED"
            if match:
                seed_undetected.append(tid)
            else:
                seed_detected_ids.append(tid)
        else:
            status = "ok" if match else "DIVERGENCE"
            if not match:
                nonseed_mismatch.append(tid)
        per_test.append({
            "id": tid,
            "is_seed": is_seed,
            "sut": s,
            "reference": rr,
            "match": match,
            "status": status,
        })

    good_corpus_passes = len(nonseed_mismatch) == 0
    seed_detected = len(seed_undetected) == 0 and len(seed_detected_ids) == len(seed_ids)
    harness_valid = good_corpus_passes and seed_detected

    report = {
        "schema": SCHEMA_REPORT,
        "work_item": "W0.4",
        "engine_internal_name": "generic-arm64-engine",
        "corpus_manifest_version": version,
        "corpus_manifest_sha256": manifest_sha,
        "sut": {
            "path": sut_path,
            "seed_active": sut.get("seed_active"),
            "engine": sut.get("engine"),
        },
        "reference": {
            "path": ref_path,
            "seed_active": ref.get("seed_active"),
            "engine": ref.get("engine"),
        },
        "counts": {
            "total": len(ids),
            "non_seed": len(ids) - len(seed_ids),
            "seed": len(seed_ids),
            "non_seed_divergences": len(nonseed_mismatch),
            "seed_detected": len(seed_detected_ids),
            "seed_undetected": len(seed_undetected),
        },
        "non_seed_divergences": nonseed_mismatch,
        "seed_undetected": seed_undetected,
        "good_corpus_passes": good_corpus_passes,
        "seed_detected": seed_detected,
        "harness_valid": harness_valid,
        "verdict": "VALID" if harness_valid else "INVALID",
        "tests": per_test,
    }
    return report


def render_text(report):
    lines = []
    lines.append("W0.4 independent differential diff report")
    lines.append("=" * 42)
    lines.append(f"corpus manifest : v{report['corpus_manifest_version']} "
                 f"sha256={report['corpus_manifest_sha256']}")
    lines.append(f"SUT (qemu/TCG)  : seed_active={report['sut']['seed_active']} "
                 f"{report['sut']['path']}")
    lines.append(f"reference (hw)  : seed_active={report['reference']['seed_active']} "
                 f"{report['reference']['path']}")
    lines.append("")
    for t in report["tests"]:
        tag = "SEED" if t["is_seed"] else "    "
        flag = "OK " if t["status"] in ("ok", "seed-detected") else "!! "
        lines.append(f"  {flag}{tag} {t['id']:<16} {t['status']:<18} "
                     f"sut={t['sut']} ref={t['reference']}")
    lines.append("")
    c = report["counts"]
    lines.append(f"non-seed tests : {c['non_seed']}  divergences: {c['non_seed_divergences']}")
    lines.append(f"seed tests     : {c['seed']}  detected: {c['seed_detected']}  "
                 f"undetected: {c['seed_undetected']}")
    lines.append(f"good corpus passes : {report['good_corpus_passes']}")
    lines.append(f"seed detected      : {report['seed_detected']}")
    lines.append(f"VERDICT            : {report['verdict']} "
                 f"(harness_valid={report['harness_valid']})")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="W0.4 differential diff engine")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sut", required=True, help="SUT (qemu-system-aarch64 / TCG) result set")
    ap.add_argument("--reference", required=True, help="ARM64 hardware reference result set")
    ap.add_argument("--out", required=True, help="diff-report.json output path")
    ap.add_argument("--text", help="optional human-readable summary output path")
    args = ap.parse_args(argv)

    try:
        report = diff(args.manifest, args.sut, args.reference)
    except StructuralError as e:
        sys.stderr.write(f"STRUCTURAL ERROR (fail-closed): {e}\n")
        return 2

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    text = render_text(report)
    if args.text:
        with open(args.text, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    sys.stdout.write(text)

    return 0 if report["harness_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
