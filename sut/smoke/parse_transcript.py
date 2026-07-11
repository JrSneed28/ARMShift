#!/usr/bin/env python3
"""Turn a captured serial transcript into machine-readable smoke-test evidence.

Consumes the raw serial log (from run_smoke.ps1), the run-result.json, and the
fixed command-manifest.json, and emits:

  * boot-transcript.json - a structured, machine-readable boot transcript
    (per-command argv/rc/stdout, guest facts, shutdown status, verdict).
  * smoke-junit.xml      - a JUnit result CI (W0.5) can gate on without a human.

Verdict is the conjunction of: reached the manifest runner (a usable shell ran
our commands), every manifest command met its expectations, the manifest
completed ok=1, and a clean guest-initiated power-off was observed while QEMU
exited 0 without hitting the harness timeout.

Exit code 0 iff every check passes. Pure stdlib.
"""
import argparse
import json
import os
import re
import sys
from xml.sax.saxutils import escape, quoteattr

# Sentinels are emitted alone on a console line; anchor to line start (after ANSI
# strip) so guest command output that merely contains a sentinel-shaped substring
# cannot open/close a command block.
ANSI_RE = re.compile(r"\x1b\[[0-9;?=]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\x1b[=>]")
BEGIN_RE = re.compile(r"^\s*=== GAE-SMOKE CMD BEGIN id=(\S+) argv=\[(.*)\] ===\s*$")
END_RE = re.compile(r"^\s*=== GAE-SMOKE CMD END id=(\S+) rc=(-?\d+) ===\s*$")
MBEGIN_RE = re.compile(r"^\s*=== GAE-SMOKE MANIFEST BEGIN version=(\d+) ===\s*$")
MEND_RE = re.compile(r"^\s*=== GAE-SMOKE MANIFEST END ok=(\d+) ===\s*$")


def normalize(raw: bytes) -> list:
    text = raw.decode("latin-1")
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ANSI_RE.sub("", text)
    return text.split("\n")


def parse_commands(lines):
    """Return {id: {"rc": int, "argv": str, "stdout": str}} for CMD blocks."""
    out = {}
    i = 0
    n = len(lines)
    while i < n:
        m = BEGIN_RE.search(lines[i])
        if not m:
            i += 1
            continue
        cid, argv = m.group(1), m.group(2)
        body = []
        j = i + 1
        rc = None
        while j < n:
            e = END_RE.search(lines[j])
            if e and e.group(1) == cid:
                rc = int(e.group(2))
                break
            body.append(lines[j])
            j += 1
        out[cid] = {"argv": argv, "rc": rc, "stdout": "\n".join(body).strip("\n")}
        i = j + 1
    return out


def first_match(lines, needle):
    for ln in lines:
        if needle in ln:
            return ln.strip()
    return None


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--run-result", required=True)
    ap.add_argument("--manifest", default=os.path.join(here, "command-manifest.json"))
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-junit", required=True)
    args = ap.parse_args()

    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(args.run_result, "r", encoding="utf-8-sig") as fh:
        run = json.load(fh)
    with open(args.transcript, "rb") as fh:
        raw = fh.read()
    lines = normalize(raw)

    parsed = parse_commands(lines)
    m_begin = any(MBEGIN_RE.search(ln) for ln in lines)
    m_end_ok = any(MEND_RE.search(ln) and ln.rstrip().endswith("ok=1 ===") for ln in lines)

    tests = []  # (classname, name, ok, message)

    # 1. reached a usable shell (the manifest runner executed in booted userspace)
    tests.append(("boot", "reached-usable-shell", m_begin,
                  "" if m_begin else "MANIFEST BEGIN sentinel not found in serial transcript"))

    # 2. per-command checks
    cmd_records = []
    for cmd in manifest["commands"]:
        cid = cmd["id"]
        expect_rc = cmd.get("expect_rc", 0)
        rec = parsed.get(cid)
        checks = []
        if rec is None:
            ok = False
            msg = "command block not found in transcript"
            cmd_records.append({"id": cid, "argv": cmd["argv"], "found": False,
                                "rc": None, "expect_rc": expect_rc, "stdout": None,
                                "checks": [], "ok": False})
        else:
            msgs = []
            rc_ok = rec["rc"] == expect_rc
            checks.append({"name": "rc==%d" % expect_rc, "ok": rc_ok})
            if not rc_ok:
                msgs.append("rc=%s expected %d" % (rec["rc"], expect_rc))
            if "expect_stdout_equals" in cmd:
                exp = cmd["expect_stdout_equals"]
                c = rec["stdout"].strip() == exp
                checks.append({"name": "stdout==%r" % exp, "ok": c})
                if not c:
                    msgs.append("stdout %r != %r" % (rec["stdout"].strip(), exp))
            if "expect_stdout_contains" in cmd:
                exp = cmd["expect_stdout_contains"]
                c = exp in rec["stdout"]
                checks.append({"name": "stdout~%r" % exp, "ok": c})
                if not c:
                    msgs.append("stdout does not contain %r" % exp)
            ok = all(ch["ok"] for ch in checks)
            msg = "; ".join(msgs)
            cmd_records.append({"id": cid, "argv": cmd["argv"], "found": True,
                                "rc": rec["rc"], "expect_rc": expect_rc,
                                "stdout": rec["stdout"], "checks": checks, "ok": ok})
        tests.append(("manifest.command", cid, ok, msg))

    # 3. manifest completed ok=1
    tests.append(("manifest", "manifest-complete", m_end_ok,
                  "" if m_end_ok else "MANIFEST END ok=1 sentinel not found"))

    # 4. clean shutdown: console marker present AND qemu exited 0 without timeout
    markers = manifest["shutdown"]["expect_console_markers_any"]
    marker_hit = None
    for mk in markers:
        if first_match(lines, mk):
            marker_hit = mk
            break
    timed_out = bool(run.get("timed_out"))
    exit_code = run.get("exit_code")
    shutdown_ok = (marker_hit is not None) and (not timed_out) and (exit_code == 0)
    sd_msg = ""
    if not shutdown_ok:
        sd_msg = "marker=%r timed_out=%s exit_code=%s" % (marker_hit, timed_out, exit_code)
    tests.append(("shutdown", "clean-poweroff", shutdown_ok, sd_msg))

    total = len(tests)
    failed = sum(1 for _, _, ok, _ in tests if not ok)
    passed = failed == 0

    # ---- guest facts for the structured transcript ----
    ds = first_match(lines, "DataSourceNoCloud")
    ci = first_match(lines, "Cloud-init v.")
    ci_ver = None
    if ci:
        mm = re.search(r"Cloud-init v\.\s*(\S+)", ci)
        ci_ver = mm.group(1) if mm else None
    os_rec = parsed.get("os_release")
    pretty = None
    if os_rec:
        pm = re.search(r'PRETTY_NAME="([^"]+)"', os_rec["stdout"])
        pretty = pm.group(1) if pm else None
    uname_rec = parsed.get("uname_a")

    boot_json = {
        "schema": "gae-smoke/boot-transcript@1",
        "work_item": "W0.3",
        "engine_internal_name": "generic-arm64-engine",
        "manifest_version": manifest["manifest_version"],
        "generated_from": {
            "transcript": os.path.basename(args.transcript),
            "run_result": os.path.basename(args.run_result),
            "command_manifest": os.path.basename(args.manifest),
        },
        "run": run,
        "guest": {
            "datasource": ds,
            "cloud_init_version": ci_ver,
            "os_release_pretty": pretty,
            "uname": uname_rec["stdout"] if uname_rec else None,
        },
        "boot": {"reached_manifest": m_begin, "manifest_ok": m_end_ok},
        "commands": cmd_records,
        "shutdown": {
            "clean": shutdown_ok,
            "console_marker": marker_hit,
            "qemu_exit_code": exit_code,
            "timed_out": timed_out,
        },
        "result": {"passed": passed, "tests_total": total, "tests_failed": failed},
    }
    with open(args.out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(boot_json, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # ---- JUnit ----
    suite_time = run.get("elapsed_seconds", 0)
    xml = []
    xml.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml.append('<testsuites name="gae-smoke-w0.3" tests="%d" failures="%d" time="%s">'
               % (total, failed, suite_time))
    xml.append('  <testsuite name="generic-arm64-guest-smoke" tests="%d" failures="%d" time="%s">'
               % (total, failed, suite_time))
    xml.append('    <properties>')
    xml.append('      <property name="engine" value="generic-arm64-engine"/>')
    xml.append('      <property name="accelerator" value="tcg"/>')
    xml.append('      <property name="guest" value=%s/>' % quoteattr(str(pretty)))
    xml.append('      <property name="qemu_version" value="11.0.2"/>')
    xml.append('      <property name="manifest_version" value="%d"/>' % manifest["manifest_version"])
    xml.append('    </properties>')
    for classname, name, ok, msg in tests:
        attrs = 'classname=%s name=%s time="0"' % (quoteattr(classname), quoteattr(name))
        if ok:
            xml.append('    <testcase %s/>' % attrs)
        else:
            xml.append('    <testcase %s>' % attrs)
            xml.append('      <failure message=%s>%s</failure>'
                       % (quoteattr(msg or "check failed"), escape(msg or "")))
            xml.append('    </testcase>')
    xml.append('  </testsuite>')
    xml.append('</testsuites>')
    with open(args.out_junit, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(xml) + "\n")

    print("PASSED" if passed else "FAILED",
          "- tests=%d failures=%d" % (total, failed))
    for classname, name, ok, msg in tests:
        print("  [%s] %s/%s %s" % ("PASS" if ok else "FAIL", classname, name,
                                    ("- " + msg) if (msg and not ok) else ""))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
