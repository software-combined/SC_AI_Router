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
# The hook helper needs 3.11+ (datetime.UTC). The POSIX shims' historical
# bare python3 stays unvalidated; anything absolute is probed before install.
POSIX_INTERPRETER = "python3"
MIN_PYTHON = (3, 11)
ROUTER_HOME_ENV = "ROUTER_HOME"
ROUTER_HOME_PARTS = (".codex", "mixed-model-router")


def router_home():
    """The SCG router home, resolved as ai_router/state.py resolves it.

    ROUTER_HOME wins; otherwise ~/.codex/mixed-model-router. Read from the
    environment so the plugin finds the router's pinned runtime without
    importing the router package.
    """
    override = os.environ.get(ROUTER_HOME_ENV)
    return Path(override) if override else Path.home().joinpath(*ROUTER_HOME_PARTS)


def resolve_interpreter(config, os_name=None):
    """The interpreter that runs the hook helper.

    An explicit absolute path in the config wins. Windows has no python3 on
    PATH, so it defaults to the router's pinned runtime instead of searching
    PATH; POSIX keeps the historical bare python3 the shims already use.
    """
    configured = config.get("interpreter")
    if configured is not None and not isinstance(configured, str):
        raise ValueError("interpreter must be an absolute path string.")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    if (os.name if os_name is None else os_name) == "nt":
        return str(router_home() / "runtime" / "python" / "python.exe")
    return POSIX_INTERPRETER


def verify_interpreter(interpreter):
    """Absolute, present, and a Python 3.11+ that actually runs."""
    path = Path(interpreter)
    if not path.is_absolute():
        raise ValueError(f"interpreter must be an absolute path: {interpreter}")
    if not path.is_file():
        raise ValueError(f"interpreter is missing: {interpreter}")
    try:
        result = subprocess.run(
            [str(path), "-c", "import sys;print('%d %d' % sys.version_info[:2])"],
            capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"interpreter did not run: {interpreter}: {exc}")
    parts = (result.stdout.strip().splitlines() or [""])[-1].split()
    try:
        version = tuple(int(part) for part in parts)
    except ValueError:
        raise ValueError(f"interpreter did not report a Python version: {interpreter}")
    if version < MIN_PYTHON:
        raise ValueError("interpreter is Python %d.%d; 3.11 or newer is required: %s"
                         % (version[0], version[1], interpreter))


def effective_config(config, os_name=None):
    """The config as installed, with the resolved interpreter recorded.

    The hook shims read this value, so a resolved absolute path is persisted;
    the POSIX python3 default is not, which keeps existing installs and their
    config bytes unchanged.
    """
    stored = dict(config)
    interpreter = resolve_interpreter(config, os_name)
    if Path(interpreter).is_absolute():
        stored["interpreter"] = interpreter
    return stored


def verify_config(config, os_name=None):
    if config.get("required_lanes") != LANES:
        raise ValueError("Configuration must require correctness, quality and adversarial lanes.")
    ttl = config.get("review_state_ttl_seconds")
    if type(ttl) is not int or not 1 <= ttl <= 86400:
        raise ValueError("Review receipt lifetime must be between 1 and 86400 seconds.")
    interpreter = resolve_interpreter(config, os_name)
    configured = isinstance(config.get("interpreter"), str) and config["interpreter"].strip()
    if configured or Path(interpreter).is_absolute():
        verify_interpreter(interpreter)
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


def provision(repo, config, install=False, home=None, os_name=None):
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
    name = os.name if os_name is None else os_name
    stored = effective_config(config, name)
    verify_config(stored, name)
    if target.exists():
        for relative in FILES:
            current = target / relative
            if not current.is_file() or current.read_bytes() != (source / relative).read_bytes():
                raise ValueError(f"Existing adapter differs or is incomplete: {relative}; no files replaced.")
            # Windows has no execute bit, so the mode check is POSIX-only.
            if (name != "nt" and relative != "lib/scg_agent_git_hooks.py"
                    and not os.access(current, os.X_OK)):
                raise ValueError(f"Existing adapter is not executable: {relative}.")
        if json.loads((target / "config.json").read_text()) != stored:
            raise ValueError("Existing scanner configuration differs; no files replaced.")
    elif install:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="scg-review-", dir=target.parent) as temporary:
            staging = Path(temporary) / "adapter"
            for relative in FILES:
                dest = staging / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, dest)
            (staging / "config.json").write_text(json.dumps(stored, indent=2) + "\n")
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
    if sys.version_info < (3, 11):
        parser.error("This adapter requires Python 3.11+.")
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
