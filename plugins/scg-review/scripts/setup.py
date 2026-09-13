#!/usr/bin/env python3
"""Check prerequisites or explicitly install the unchanged shared hook adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

PLUGIN = Path(__file__).resolve().parents[1]
FILES = ("pre-commit", "commit-msg", "bin/scg-review-state", "lib/scg_agent_git_hooks.py")
LANES = ["correctness", "quality", "adversarial"]


def verify_config(config):
    if config.get("required_lanes") != LANES:
        raise ValueError("Configuration must require correctness, quality and adversarial lanes.")
    ttl = config.get("review_state_ttl_seconds")
    if type(ttl) is not int or not 1 <= ttl <= 86400:
        raise ValueError("Review receipt lifetime must be between 1 and 86400 seconds.")
    pin = config.get("gitleaks", {})
    binary = Path(pin.get("binary", ""))
    digest = pin.get("sha256", "")
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("Pinned Gitleaks must be an absolute executable file path.")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Gitleaks needs an approved lowercase SHA-256.")
    if not pin.get("provenance") or not isinstance(pin.get("version"), str):
        raise ValueError("Gitleaks needs an approved version and provenance.")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != digest:
        raise ValueError("Gitleaks checksum differs from its approved pin; executable was not run.")
    timeout = pin.get("timeout_seconds", 60)
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ValueError("Scanner timeout must be between 1 and 300 seconds.")
    result = subprocess.run([str(binary), "version"], capture_output=True, text=True,
                            check=True, timeout=timeout)
    if (result.stdout.strip().splitlines() or [""])[-1] != pin["version"]:
        raise ValueError("Gitleaks version differs from its approved pin.")


def provision(repo, config, install=False, home=None):
    home = Path.home() if home is None else Path(home)
    target = home / ".config/scg-agent-git-hooks"
    source = PLUGIN / "support/git-hooks"
    repo = Path(repo).resolve(strict=True)
    subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                   capture_output=True, text=True, check=True)
    result = subprocess.run(["git", "-C", str(repo), "config", "--path", "--get", "core.hooksPath"],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise ValueError("Could not inspect effective core.hooksPath.")
    configured = result.stdout.strip()
    if configured and Path(configured).resolve() != target.resolve():
        raise ValueError("A different core.hooksPath is configured; preserve it and arrange a migration.")
    if not install and not configured:
        raise ValueError("Repository has no SCG core.hooksPath; explicit setup is required.")
    verify_config(config)
    if target.exists():
        for relative in FILES:
            current = target / relative
            if not current.is_file() or current.read_bytes() != (source / relative).read_bytes():
                raise ValueError(f"Existing adapter differs or is incomplete: {relative}; no files replaced.")
            if relative != "lib/scg_agent_git_hooks.py" and not os.access(current, os.X_OK):
                raise ValueError(f"Existing adapter is not executable: {relative}.")
        if json.loads((target / "config.json").read_text()) != config:
            raise ValueError("Existing scanner configuration differs; no files replaced.")
    elif install:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="scg-review-", dir=target.parent) as temporary:
            staging = Path(temporary) / "adapter"
            for relative in FILES:
                dest = staging / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, dest)
            (staging / "config.json").write_text(json.dumps(config, indent=2) + "\n")
            staging.rename(target)
    else:
        raise ValueError("Shared adapter is missing; explicit setup is required.")
    if install:
        subprocess.run(["git", "-C", str(repo), "config", "--local", "core.hooksPath", str(target)],
                       check=True, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "install"))
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="Owner-reviewed config; required for install")
    args = parser.parse_args()
    if sys.version_info < (3, 11) or os.name != "posix":
        parser.error("This adapter requires macOS/Linux and Python 3.11+.")
    if args.command == "install" and not args.config:
        parser.error("install requires --config with an owner-reviewed scanner pin")
    config_path = args.config or Path.home() / ".config/scg-agent-git-hooks/config.json"
    try:
        config = json.loads(config_path.read_text())
        provision(args.repo, config, args.command == "install")
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        print(f"SCG review setup BLOCKED: {exc}", file=sys.stderr)
        return 1
    print("Local hook and scanner prerequisites passed. Model access and actual review remain separate gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
