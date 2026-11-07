#!/usr/bin/env python3
"""Vendor-side license tool - NOT shipped to customers.

Usage:
  license_keygen.py init                 generate the vendor keypair ONCE;
                                         prints the public key to embed in
                                         licensing.py PUBLIC_KEY_B64 and
                                         saves the private key OUTSIDE the repo
  license_keygen.py sign --licensee NAME [--seats N]
                         [--expires YYYY-MM-DD]
                         [--features a,b,c] [--out FILE]

The private key lives in a vendor secrets dir (default
%SHIELDAI_VENDOR_KEY% or ~/.shieldai-vendor/ed25519.key). If it leaks,
anyone can forge licenses - treat it like a CA key.
"""
import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _key_path() -> Path:
    env = os.environ.get("SHIELDAI_VENDOR_KEY")
    if env:
        return Path(env)
    return Path.home() / ".shieldai-vendor" / "ed25519.key"


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def cmd_init() -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 \
        import Ed25519PrivateKey
    kp = _key_path()
    if kp.exists():
        print(f"keypair already exists at {kp} - refusing to overwrite")
        return 1
    kp.parent.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    kp.write_bytes(priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption()))
    os.chmod(kp, 0o600)
    pub_b64 = base64.b64encode(priv.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw)).decode()
    print(f"[OK] private key: {kp} (chmod 600 - NEVER commit this)")
    print(f"[OK] embed this in src/guardian_ai/licensing.py PUBLIC_KEY_B64:")
    print(f"     {pub_b64}")
    return 0


def cmd_sign(args) -> int:
    from cryptography.hazmat.primitives.asymmetric.ed25519 \
        import Ed25519PrivateKey
    kp = _key_path()
    if not kp.exists():
        print(f"no private key at {kp} - run 'init' first")
        return 1
    priv = Ed25519PrivateKey.from_private_bytes(kp.read_bytes())
    lic = {"product": "ShieldAI",
           "licensee": args.licensee,
           "seats": args.seats,
           "issued": datetime.now(timezone.utc).isoformat(),
           "expires": args.expires,
           "features": args.features.split(",") if args.features else []}
    sig = base64.b64encode(priv.sign(_canonical(lic))).decode()
    doc = {"license": lic, "signature": sig}
    out = Path(args.out or f"shieldai-{args.licensee}.license")
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"[OK] signed license: {out}")
    print(f"     deliver to customer; they place it in their data dir")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("sign")
    s.add_argument("--licensee", required=True)
    s.add_argument("--seats", type=int, default=1)
    s.add_argument("--expires", default=None,
                   help="YYYY-MM-DD (omit for perpetual)")
    s.add_argument("--features", default="")
    s.add_argument("--out", default=None)
    args = p.parse_args()
    if getattr(args, "expires", None):
        args.expires = datetime.fromisoformat(args.expires).replace(
            tzinfo=timezone.utc).isoformat()
    return cmd_init() if args.cmd == "init" else cmd_sign(args)


if __name__ == "__main__":
    sys.exit(main())
