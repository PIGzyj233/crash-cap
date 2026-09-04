"""Inspect or reset only the dedicated Crash-Cap first-launch Compose data."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "crash-cap-phase1"
VOLUMES = {
    "crashcap_phase1_" + name
    for name in ("company_sdk", "postgres", "redis", "rustfs", "symbolicator", "symbols")
}


def docker(*args: str) -> str:
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, encoding="utf-8", timeout=240
    ).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--reset-data", action="store_true", help="Delete verified project data")
    args = parser.parse_args()
    env_file = args.env_file.resolve(strict=True)
    compose = [
        "compose", "--env-file", str(env_file), "-f",
        str(ROOT / "deploy/compose/phase1.yml"), "-p", PROJECT,
    ]
    config = json.loads(docker(*compose, "config", "--format", "json"))
    configured = {volume["name"] for volume in config["volumes"].values()}
    if configured != VOLUMES or any(v.get("external") for v in config["volumes"].values()):
        raise RuntimeError("Compose volumes differ from the dedicated first-launch allowlist")
    existing_names = set(docker("volume", "ls", "--format", "{{.Name}}").splitlines())
    inventory = []
    for name in sorted(VOLUMES & existing_names):
        volume = json.loads(docker("volume", "inspect", name))[0]
        if (volume.get("Labels") or {}).get("com.docker.compose.project") != PROJECT:
            raise RuntimeError(f"Volume ownership mismatch: {name}")
        inventory.append({"name": name, "project": PROJECT})
    ids = docker("ps", "-aq").split()
    containers = json.loads(docker("inspect", *ids)) if ids else []
    mounts = []
    reset_volumes = set(VOLUMES)
    for container in containers:
        owner = (container["Config"].get("Labels") or {}).get("com.docker.compose.project")
        for mount in container["Mounts"]:
            if mount["Type"] != "volume":
                continue
            name = mount["Name"]
            if owner == PROJECT:
                if name not in VOLUMES:
                    volume = json.loads(docker("volume", "inspect", name))[0]
                    if (
                        "com.docker.volume.anonymous" not in (volume.get("Labels") or {})
                        or mount["Destination"] not in (container["Config"].get("Volumes") or {})
                    ):
                        raise RuntimeError(f"Project container has an unexpected volume: {name}")
                    reset_volumes.add(name)
                    inventory.append({"name": name, "project": PROJECT, "anonymous": True})
                mounts.append({"container": container["Name"], "volume": name})
    for container in containers:
        owner = (container["Config"].get("Labels") or {}).get("com.docker.compose.project")
        if owner != PROJECT and any(
            m["Type"] == "volume" and m["Name"] in reset_volumes for m in container["Mounts"]
        ):
            raise RuntimeError(f"A foreign container uses project data: {container['Name']}")
    output = ROOT / "target/qa-first-launch"
    output.mkdir(parents=True, exist_ok=True)
    receipt = {"project": PROJECT, "volumes": inventory, "mounts": mounts, "reset": False}
    path = output / "reset-inventory.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(inventory)} dedicated volumes; inventory: {path}", flush=True)
    if not args.reset_data:
        return
    docker(*compose, "down", "--volumes", "--remove-orphans")
    remaining = reset_volumes & set(docker("volume", "ls", "--format", "{{.Name}}").splitlines())
    if remaining:
        raise RuntimeError(f"Reset incomplete: {sorted(remaining)}")
    receipt["reset"] = True
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Dedicated data removed. Start the stack with the same Compose env file.", flush=True)


if __name__ == "__main__":
    main()
