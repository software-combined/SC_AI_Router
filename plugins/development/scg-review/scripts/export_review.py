#!/usr/bin/env python3
"""Export a committed local review without paths, free text or credentials."""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import re


def export_review(verification_urls: list[str]) -> dict:
    source = Path(__file__).resolve().parents[1] / "support/git-hooks/lib/scg_agent_git_hooks.py"
    spec = importlib.util.spec_from_file_location("scg_review_export_hook", source)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    config = hook.load_config()
    info = hook.repo_info()
    commit = hook.git(["rev-parse", "HEAD"])
    if hook.git(["status", "--porcelain", "--untracked-files=no"]):
        hook.fail("Commit the reviewed change before exporting its evidence.")
    if hook.git(["rev-parse", "HEAD^{tree}"]) != info["tree"]:
        hook.fail("The committed tree differs from the review scope.")
    candidates = hook.load_candidate_states(info)
    if len(candidates) != 1 or candidates[0][2] != "loaded":
        hook.fail("No readable review receipt exists for the committed tree.")
    state = candidates[0][1]
    valid, reason = hook.state_is_valid(
        state, info, config, int(config.get("review_state_ttl_seconds", 86400)),
    )
    if not valid:
        hook.fail(f"Review export refused: {reason}.")
    origin = hook.git(["remote", "get-url", "origin"])
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", origin)
    if not match:
        hook.fail("Review export requires a GitHub origin without embedded credentials.")
    repository = match[1]
    prefix = f"https://github.com/{repository}/actions/runs/"
    if any(not url.startswith(prefix) or not re.fullmatch(r"[0-9]+/?", url[len(prefix):])
           for url in verification_urls):
        hook.fail("Verification references must be Actions run URLs in this repository.")
    passes = state["passes"]
    if any(not re.fullmatch(r"[a-z]+", lane) or not isinstance(value, str)
           or not re.fullmatch(r"[A-Za-z0-9_./:@-]{1,300}", value)
           for lane, value in passes.items()):
        hook.fail("Review identities must contain only model and effort identifiers.")
    return {
        "version": 1,
        "repository": repository,
        "commit": commit,
        "tree": info["tree"],
        "decision": state["decision"],
        "reviewed_at": dt.datetime.fromtimestamp(state["created_at_epoch"], dt.UTC).isoformat(),
        "passes": passes,
        "verification_urls": verification_urls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification-url", action="append", required=True,
                        help="Passing GitHub Actions run URL for this repository; repeat as needed")
    args = parser.parse_args()
    print(json.dumps(export_review(args.verification_url), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
