#!/usr/bin/env python3
"""Render the W0.4 corpus-boot NoCloud seed for the SUT lane.

Embeds the SHARED static aarch64 corpus_runner (the SAME binary the native ARM64
reference lane built and ran, carried in reference/corpus_runner.b64) into the
pinned Alpine guest, runs it under TCG, and emits its stdout base64-encoded and
sentinel-bracketed over the serial console (base64 so the tab-separated lines
survive verbatim), then powers off cleanly.

Running the identical static binary on both sides is the W0.4 fidelity property:
the differential then isolates TCG translation semantics, not build differences.
This script fails closed unless the embedded binary's SHA-256 equals the pinned
reference binary hash.

Usage:
  python render_corpus_seed.py --runner-b64 reference/corpus_runner.b64 \
      --runner-sha256 reference/corpus_runner.sha256 --out <seed_dir>
"""
import argparse
import base64
import hashlib
import os


def render_user_data(runner_b64_oneline: str) -> str:
    lines = []
    lines.append("#cloud-config")
    lines.append("# generic-arm64-engine - W0.5 SUT-lane W0.4 corpus boot (NoCloud seed).")
    lines.append("# Embeds the shared static aarch64 corpus_runner, runs it under TCG, and")
    lines.append("# emits its stdout base64-encoded + sentinel-bracketed to the serial console.")
    lines.append("hostname: gae-corpus")
    lines.append("write_files:")
    lines.append("  - path: /root/corpus_runner")
    lines.append("    permissions: '0755'")
    lines.append("    owner: root:root")
    lines.append("    encoding: b64")
    lines.append("    content: |")
    lines.append("      " + runner_b64_oneline)
    lines.append("  - path: /root/gae-corpus.sh")
    lines.append("    permissions: '0755'")
    lines.append("    owner: root:root")
    lines.append("    content: |")
    runner = []
    runner.append("#!/bin/sh")
    runner.append("# Runs the shared static corpus_runner; emits base64 output between sentinels.")
    runner.append("CON=/dev/console")
    runner.append("emit() { printf '%s\\n' \"$*\" > \"$CON\"; }")
    runner.append("emit \"=== GAE-CORPUS BEGIN ===\"")
    runner.append("out=\"$(/root/corpus_runner)\"; rc=$?")
    # busybox base64 has no -w flag; strip any wrapping newlines with tr for portability.
    runner.append("b64=\"$(printf '%s' \"$out\" | base64 | tr -d '\\n')\"")
    runner.append("emit \"GAE-CORPUS-B64 ${b64}\"")
    runner.append("emit \"=== GAE-CORPUS END rc=${rc} ===\"")
    for r in runner:
        lines.append("      " + r)
    lines.append("runcmd:")
    lines.append("  - [ /bin/sh, /root/gae-corpus.sh ]")
    lines.append("power_state:")
    lines.append("  mode: poweroff")
    lines.append("  message: gae-corpus complete, powering off")
    lines.append("  timeout: 60")
    lines.append("  condition: true")
    return "\n".join(lines) + "\n"


def render_meta_data() -> str:
    return "instance-id: gae-corpus-w0.5-v1\nlocal-hostname: gae-corpus\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the W0.4 corpus-boot NoCloud seed")
    ap.add_argument("--runner-b64", required=True, help="reference/corpus_runner.b64 (single-line base64)")
    ap.add_argument("--runner-sha256", required=True, help="reference/corpus_runner.sha256")
    ap.add_argument("--out", required=True, help="output seed directory")
    args = ap.parse_args()

    with open(args.runner_b64, "r", encoding="ascii") as fh:
        b64_oneline = "".join(fh.read().split())  # strip all whitespace/newlines -> single line
    raw = base64.b64decode(b64_oneline)
    got = hashlib.sha256(raw).hexdigest()
    with open(args.runner_sha256, "r", encoding="ascii") as fh:
        expected = fh.read().split()[0].strip().lower()
    if got.lower() != expected:
        raise SystemExit("FAIL: embedded corpus_runner SHA-256 %s != pinned reference %s"
                         % (got, expected))
    print("embedded corpus_runner sha256 matches reference: %s (%d bytes)" % (got, len(raw)))

    os.makedirs(args.out, exist_ok=True)
    ud = render_user_data(b64_oneline)
    md = render_meta_data()
    with open(os.path.join(args.out, "user-data"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ud)
    with open(os.path.join(args.out, "meta-data"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    print("wrote %s/user-data (%d bytes)" % (args.out, len(ud.encode("utf-8"))))
    print("wrote %s/meta-data" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
