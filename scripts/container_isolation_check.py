#!/usr/bin/env python3
"""Check the outer container and inner Bubblewrap boundaries without a model."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


def _is_socket(path: Path) -> bool:
    try:
        return stat.S_ISSOCK(path.stat().st_mode)
    except FileNotFoundError:
        return False


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    bwrap = shutil.which("bwrap")
    parent_network_namespace = os.readlink("/proc/self/ns/net")
    result: dict[str, object] = {
        "schema_version": 1,
        "run_class": "container_check",
        "experimental_data": False,
        "container_marker": Path("/.dockerenv").is_file(),
        "docker_socket_visible": any(_is_socket(Path(path)) for path in ("/run/docker.sock", "/var/run/docker.sock")),
        "bubblewrap_available": bwrap is not None,
        "outer_controller_only_docker_access": True,
    }
    errors: list[str] = []
    if not result["container_marker"]:
        errors.append("Docker container marker /.dockerenv is missing")
    if result["docker_socket_visible"]:
        errors.append("Docker socket is visible inside the matrix container")
    if bwrap is None:
        errors.append("bubblewrap is unavailable")
    else:
        command = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-net",
            "--tmpfs",
            "/",
            "--proc",
            "/proc",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--dev",
            "/dev",
            "--",
            "/usr/bin/readlink",
            "/proc/self/ns/net",
        ]
        if Path("/lib64").exists():
            command[command.index("--dev"):command.index("--dev")] = ["--ro-bind", "/lib64", "/lib64"]
        child = subprocess.run(command, capture_output=True, text=True, check=False)
        child_network_namespace = child.stdout.strip()
        result["bubblewrap_exit_code"] = child.returncode
        result["outer_network_namespace"] = parent_network_namespace
        result["inner_network_namespace"] = child_network_namespace
        result["bubblewrap_unshared_network"] = (
            child.returncode == 0
            and bool(child_network_namespace)
            and child_network_namespace != parent_network_namespace
        )
        if not result["bubblewrap_unshared_network"]:
            errors.append("Bubblewrap did not produce a distinct network namespace")
    result["valid"] = not errors
    result["errors"] = errors
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        _write(args.output, result)
        sys.stdout.write(f"wrote {args.output}\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
