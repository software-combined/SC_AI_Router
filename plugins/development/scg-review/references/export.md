# Share review evidence with a pull request

After completing the installed pre-commit review and committing, run:

```sh
python3 <plugin-root>/scripts/export_review.py \
  --verification-url https://github.com/OWNER/REPOSITORY/actions/runs/RUN_ID
```

The command writes JSON to standard output. Put it in the PR's review evidence
details or attach it as a private repository artifact. Repeat the argument for
additional verification runs. Use the current plugin root from the client's
skill catalogue, never an old cache version. Both Codex and Claude Code use
the same script.

The export binds the current committed tree and commit to an existing, valid
local review receipt. Git's latest branch reflog transition must name current
HEAD as its new object and identify the commit operation. Ordinary, merge and
cherry-pick commits use their first parent, including resolved cherry-pick
continuations. Root commits use `null`. Amendments use the replaced HEAD recorded
as the old object in that transition. Both amendment revisions must have the
same parents.
Switching away from the branch and back preserves this evidence.
It checks the same repository, branch,
age, decision and required lanes as the hook. Commit the final reviewed change
first. A later tracked edit or an expired receipt requires the applicable review procedure;
the exporter cannot approve or refresh evidence.

Keep the relevant reflog until export is complete. If it is missing, ambiguous
or lacks a valid amendment predecessor, export stops. Preserve the receipts and
ensure this repository records a readable Git reflog. Review the current tree
and create a new regular commit before exporting again.

Only the repository name, commit, base commit, tree, review time, decision,
lane identifiers and verification links leave the machine. Receipt paths, host names, agent
names and free-text summaries are excluded. Verification links must identify
Actions runs in the origin repository and contain no query string.

The exporter validates link format, not a run's result or source revision.
The delivery workflow must check those in GitHub before using the evidence.
An exported receipt is a record of the local review, not cryptographic proof
of a reviewer identity. Preserve `unverified` identities as recorded.

Version 0.7.2 requires the [adapter refresh](setup.md#refresh-an-existing-installation)
and a new review. Existing receipts stay saved; the exporter cannot upgrade them.
Router delivery and fresh-session plugin availability remain separate from
source integration.
