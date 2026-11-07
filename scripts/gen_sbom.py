#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM (sbom.cyclonedx.json).

Commercial/government buyers increasingly require an SBOM - EO 14028
(US federal procurement) and the EU Cyber Resilience Act both move it
toward mandatory. ShieldAI ships exactly one runtime dependency
(cryptography), so a hand-maintained manifest stays honest and cheap
instead of a full lockfile scanner. The script still READS the installed
versions - it never hardcodes them, so the SBOM can't drift from reality.

  python scripts/gen_sbom.py            -> dist/sbom.cyclonedx.json
"""
import json
import subprocess
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DIST = ROOT / "dist"

# every runtime dep the shipped product actually imports - keep in sync
# with requirements.txt (cryptography is the ONLY hard dependency).
RUNTIME_DEPS = ["cryptography"]


def main() -> int:
    components = []
    for name in RUNTIME_DEPS:
        try:
            ver = version(name)
        except PackageNotFoundError:
            print(f"[WARN] {name} not installed - SBOM incomplete",
                  file=sys.stderr)
            continue
        components.append({
            "type": "library",
            "bom-ref": f"pkg:pypi/{name}@{ver}",
            "name": name,
            "version": ver,
            "purl": f"pkg:pypi/{name}@{ver}",
            "scope": "required",
        })
    from guardian_ai import __version__ as app_ver  # noqa
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {"type": "application",
                          "name": "ShieldAI",
                          "bom-ref": "pkg:generic/shieldai",
                          "version": app_ver},
            "tools": [{"vendor": "ShieldAI",
                       "name": "gen_sbom.py"}],
        },
        "components": components,
        "dependencies": [{
            "ref": "pkg:generic/shieldai",
            "dependsOn": [c["bom-ref"] for c in components],
        }],
    }
    DIST.mkdir(exist_ok=True)
    out = DIST / "sbom.cyclonedx.json"
    out.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
    print(f"[OK] {out} ({len(components)} components)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main())
