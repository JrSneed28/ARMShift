#!/usr/bin/env python3
"""Verify/prepare the pinned SUT-lane inputs for the W0.5 public CI (Linux).

Linux analog of the W0.3 prepare_inputs.py, driven by sut/pins.json:

  * decompresses the UEFI firmware (edk2-aarch64-code.fd, edk2-arm-vars.fd) from
    the signature-verified QEMU 11.0.2 source tree's pc-bios/ and verifies both
    the .bz2 and the decompressed .fd SHA-256 (byte-identical to the W0.3 pins);
  * ensures the pinned generic Alpine aarch64 guest image is present with the
    pinned SHA-256, downloading it over HTTPS if absent and verifying both the
    upstream-published SHA-512 and the pinned SHA-256 before use.

Any missing input or hash mismatch aborts non-zero (fail-closed). Pure stdlib.
The QEMU binary itself is rebuilt from source by build_qemu.sh (its hash is
recorded per run, not pinned), so this script does not re-hash the binary.
"""
import argparse
import bz2
import hashlib
import json
import os
import sys
import urllib.request


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sha512_file(path, chunk=1 << 20):
    h = hashlib.sha512()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def die(msg):
    print("FAIL:", msg, file=sys.stderr)
    sys.exit(1)


def require_hash(path, expected, label):
    if not os.path.isfile(path):
        die("%s: file not found: %s" % (label, path))
    got = sha256_file(path)
    if got.lower() != expected.lower():
        die("%s: SHA-256 mismatch for %s\n  expected %s\n  got      %s"
            % (label, path, expected, got))
    print("  OK  %-22s %s" % (label, expected))


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--pins", default=os.path.join(here, "pins.json"))
    ap.add_argument("--src-tree", required=True,
                    help="path to the extracted, signature-verified qemu-11.0.2 source tree")
    ap.add_argument("--firmware-dir", required=True,
                    help="output dir for the decompressed .fd firmware files")
    ap.add_argument("--image-path", required=True,
                    help="local path for the pinned guest image (downloaded if absent)")
    ap.add_argument("--allow-download", action="store_true")
    args = ap.parse_args()

    with open(args.pins, "r", encoding="utf-8") as fh:
        pins = json.load(fh)

    print("== UEFI firmware (from pinned QEMU source) ==")
    os.makedirs(args.firmware_dir, exist_ok=True)
    out = {}
    for key in ("code", "vars"):
        fw = pins["firmware"][key]
        src_bz2 = os.path.join(args.src_tree, fw["source_bz2_relpath"])
        require_hash(src_bz2, fw["source_bz2_sha256"], "edk2-%s.bz2" % key)
        dst = os.path.join(args.firmware_dir,
                           os.path.basename(fw["source_bz2_relpath"])[:-4])  # strip .bz2
        need = True
        if os.path.isfile(dst):
            need = sha256_file(dst).lower() != fw["decompressed_sha256"].lower()
        if need:
            with bz2.open(src_bz2, "rb") as src, open(dst, "wb") as d:
                d.write(src.read())
            print("  ..  decompressed %s" % os.path.basename(dst))
        require_hash(dst, fw["decompressed_sha256"], "edk2-%s.fd" % key)
        if os.path.getsize(dst) != fw["bytes"]:
            die("edk2-%s.fd size mismatch" % key)
        out["firmware_%s_fd" % key] = dst

    print("== Guest image (pinned redistributable) ==")
    gi = pins["guest_image"]
    path = args.image_path
    have = os.path.isfile(path) and sha256_file(path).lower() == gi["sha256"].lower()
    if not have:
        if not args.allow_download:
            die("guest image missing/mismatched and --allow-download not set: %s" % path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        print("  ..  downloading %s" % gi["url"])
        req = urllib.request.Request(gi["url"], headers={"User-Agent": "generic-arm64-engine"})
        with urllib.request.urlopen(req, timeout=1200) as resp, open(path, "wb") as o:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                o.write(chunk)
    if os.path.getsize(path) != gi["bytes"]:
        die("guest image size mismatch: %d != %d" % (os.path.getsize(path), gi["bytes"]))
    got512 = sha512_file(path)
    if got512.lower() != gi["sha512_recorded"].lower():
        die("guest image recorded SHA-512 mismatch")
    print("  OK  recorded SHA-512    %s" % gi["sha512_recorded"])
    require_hash(path, gi["sha256"], "guest image")
    out["guest_image"] = path

    print("\nAll pinned SUT-lane inputs verified.")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
