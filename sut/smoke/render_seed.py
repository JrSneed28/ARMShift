#!/usr/bin/env python3
"""Compile the fixed W0.3 command manifest into a cloud-init NoCloud seed.

`command-manifest.json` is the single source of truth for what the smoke test
runs. This script renders it into `user-data` (a #cloud-config that writes and
executes a sentinel-delimited manifest runner on the guest serial console, then
powers off cleanly) and a matching `meta-data`. Keeping the runner generated
from the manifest guarantees the executed commands cannot drift from the
reviewed, version-controlled manifest.

Usage:
    python render_seed.py --manifest command-manifest.json --out <seed_dir>

Writes <seed_dir>/user-data and <seed_dir>/meta-data. Pure stdlib; deterministic
(no timestamps or randomness), so the seed is byte-reproducible from the manifest.
"""
import argparse
import json
import os


def shquote(s: str) -> str:
    """POSIX single-quote a token for safe embedding in the runner script."""
    return "'" + s.replace("'", "'\\''") + "'"


def render_user_data(manifest: dict) -> str:
    version = manifest["manifest_version"]
    lines = []
    lines.append("#cloud-config")
    lines.append("# generic-arm64-engine - W0.3 generic guest smoke test (NoCloud seed).")
    lines.append("# GENERATED from command-manifest.json by render_seed.py - do not edit by hand.")
    lines.append("# Runs the fixed command manifest, streaming sentinel-delimited output to the")
    lines.append("# serial console (/dev/console == ttyAMA0), then powers off cleanly.")
    lines.append("hostname: gae-smoke")
    lines.append("write_files:")
    lines.append("  - path: /root/gae-smoke-manifest.sh")
    lines.append("    permissions: '0755'")
    lines.append("    owner: root:root")
    lines.append("    content: |")
    runner = []
    runner.append("#!/bin/sh")
    runner.append("# Fixed W0.3 command manifest runner (generated). Emits machine-parseable sentinels.")
    runner.append("CON=/dev/console")
    runner.append("emit() { printf '%s\\n' \"$*\" > \"$CON\"; }")
    runner.append("run() {")
    runner.append("  cid=\"$1\"; shift")
    runner.append("  emit \"=== GAE-SMOKE CMD BEGIN id=${cid} argv=[$*] ===\"")
    runner.append("  out=\"$(\"$@\" 2>&1)\"; rc=$?")
    runner.append("  printf '%s\\n' \"$out\" > \"$CON\"")
    runner.append("  emit \"=== GAE-SMOKE CMD END id=${cid} rc=${rc} ===\"")
    runner.append("}")
    runner.append('emit "=== GAE-SMOKE MANIFEST BEGIN version=%d ==="' % version)
    for cmd in manifest["commands"]:
        toks = [cmd["id"]] + list(cmd["argv"])
        runner.append("run " + " ".join(shquote(t) for t in toks))
    runner.append('emit "=== GAE-SMOKE MANIFEST END ok=1 ==="')
    for r in runner:
        lines.append("      " + r)
    lines.append("runcmd:")
    lines.append("  - [ /bin/sh, /root/gae-smoke-manifest.sh ]")
    lines.append("power_state:")
    lines.append("  mode: poweroff")
    lines.append("  message: gae-smoke complete, powering off")
    lines.append("  timeout: 60")
    lines.append("  condition: true")
    return "\n".join(lines) + "\n"


def render_meta_data(manifest: dict) -> str:
    version = manifest["manifest_version"]
    return (
        "instance-id: gae-smoke-w0.3-v%d\n"
        "local-hostname: gae-smoke\n" % version
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Render NoCloud seed from the fixed command manifest")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--manifest", default=os.path.join(here, "command-manifest.json"))
    ap.add_argument("--out", required=True, help="output seed directory (user-data, meta-data)")
    args = ap.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    os.makedirs(args.out, exist_ok=True)
    ud = render_user_data(manifest)
    md = render_meta_data(manifest)
    # Write with LF newlines regardless of host so the seed is byte-reproducible.
    with open(os.path.join(args.out, "user-data"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ud)
    with open(os.path.join(args.out, "meta-data"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    print("wrote %s/user-data (%d bytes)" % (args.out, len(ud.encode("utf-8"))))
    print("wrote %s/meta-data (%d bytes)" % (args.out, len(md.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
