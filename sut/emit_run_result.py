#!/usr/bin/env python3
"""Emit run-result.json (gae-smoke/run-result@1) for the SUT-lane guest boot.

Called by run_guest.sh with all values as argv (no source interpolation), so
paths and hashes are passed safely. parse_transcript.py consumes elapsed_seconds,
timed_out, and exit_code from this file; the rest is provenance (host facts,
input hashes) retained as evidence.
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess


def sha256(path):
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--qemu", required=True)
    ap.add_argument("--qemu-sha", required=True)
    ap.add_argument("--cpu", required=True)
    ap.add_argument("--smp", required=True)
    ap.add_argument("--mem", required=True)
    ap.add_argument("--code-fd", required=True)
    ap.add_argument("--vars-fd", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--started", required=True)
    ap.add_argument("--ended", required=True)
    ap.add_argument("--elapsed", required=True, type=int)
    ap.add_argument("--timeout", required=True, type=int)
    ap.add_argument("--timed-out", required=True)
    ap.add_argument("--exit-code", required=True, type=int)
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--transcript-sha", default="")
    ap.add_argument("--qerr", required=True)
    a = ap.parse_args()

    cpu_model = sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //'") or platform.machine()
    res = {
        "schema": "gae-smoke/run-result@1",
        "work_item": "W0.5",
        "engine_internal_name": "generic-arm64-engine",
        "accelerator": "tcg",
        "host": {
            "runner": "github-actions ubuntu-latest (public hosted)",
            "kernel": sh("uname -sr"),
            "arch": platform.machine(),
            "cpu_model": cpu_model,
        },
        "qemu": {
            "binary": a.qemu,
            "sha256": a.qemu_sha,
            "cpu": a.cpu,
            "smp": int(a.smp),
            "mem_mib": int(a.mem),
        },
        "inputs": {
            "code_fd": {"path": a.code_fd, "sha256": sha256(a.code_fd)},
            "vars_fd_source": {"path": a.vars_fd, "sha256": sha256(a.vars_fd)},
            "image": {"path": a.image, "sha256": sha256(a.image)},
            "seed": {"path": a.seed, "sha256": sha256(a.seed)},
        },
        "started_utc": a.started,
        "ended_utc": a.ended,
        "elapsed_seconds": a.elapsed,
        "timeout_seconds": a.timeout,
        "timed_out": (a.timed_out == "true"),
        "exit_code": a.exit_code,
        "transcript_path": a.transcript,
        "transcript_sha256": a.transcript_sha,
        "qemu_stderr_path": a.qerr,
    }
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
