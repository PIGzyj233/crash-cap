"""Load the current read-only qualifier into an explicitly named local container."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "target/qa-symbol-import/legacy-qualification.json",
    )
    args = parser.parse_args()
    modules = {
        name: (SCRIPTS / (name + ".py")).read_text(encoding="utf-8")
        for name in ("protocol", "legacy_continuity")
    }
    inventory = (SCRIPTS / "legacy_inventory.py").read_text(encoding="utf-8")
    # Structured stdin avoids shell quoting, container mounts, and code copies.
    wrapper = "import sys, types, json\n"
    wrapper += "sources = " + repr(modules) + "\n"
    wrapper += "for name, source in sources.items():\n    module = types.ModuleType(name)\n    sys.modules[name] = module\n    exec(compile(source, name + '.py', 'exec'), module.__dict__)\n"
    wrapper += "sys.argv = ['legacy_inventory.py', '--qualify', '--limit', '200']\n"
    wrapper += "exec(compile(" + repr(inventory) + ", 'legacy_inventory.py', 'exec'))\n"
    result = subprocess.run(
        ["docker", "exec", "-i", args.container, "python", "-"],
        input=wrapper,
        text=True,
        capture_output=True,
        timeout=120,
        cwd=ROOT,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    report = json.loads(result.stdout)
    report["container"] = args.container
    report["qualification_code_sha256"] = {
        name: hashlib.sha256(text.encode()).hexdigest()
        for name, text in {**modules, "legacy_inventory": inventory}.items()
    }
    report["qualification_summary"] = {
        "runs": len(report["runs"]),
        "anchors_verified": sum(
            r["legacy_qualification"]["anchor_status"] == "verified"
            for r in report["runs"]
        ),
        "incomparable": sum(
            r["legacy_qualification"]["anchor_status"] == "incomparable"
            for r in report["runs"]
        ),
        "current_runs": sum(r["is_current"] for r in report["runs"]),
        "automatically_promoted": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                **report["qualification_summary"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
