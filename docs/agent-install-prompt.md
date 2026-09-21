# Router install prompt for your agent

Paste this to your coding agent (Codex, Claude Code) after downloading the
bootstrap for your OS from `https://dist.softwarecombined.com/bootstrap/`.
The agent runs everything; you only approve restarts.

> Set up the SCG mixed-model router on this machine. The bootstrap files
> (`bootstrap.sh` for macOS/Linux, `bootstrap.ps1` for Windows) are in my
> downloads from `https://dist.softwarecombined.com/bootstrap/`.
>
> Steps: run the bootstrap for my OS, then verify with the
> installer `--preflight` and `--status` probes against the default home
> and show me the redacted summary. A key window opens by itself when the
> key is missing: never handle the key yourself, never ask me for it in
> chat, and tell me to paste it in the window. If no window appears,
> re-run the installer with `--setup`. If anything fails, stop and show me
> the exact error, do not retry with different flags.
>
> Before attaching, ask me which assistant I use (ChatGPT, Claude, or both)
> and where: the desktop app, the terminal, or both. Then run the installer
> once with the matching flags and show me its output:
> ChatGPT `--clients codex` (its app and terminal share one attachment);
> Claude terminal `--clients claude`; Claude app `--clients none --desktop`;
> both Claude surfaces `--clients claude --desktop`; both assistants in the
> terminal `--clients both`; both assistants in the apps `--clients codex
> --desktop`; both assistants everywhere `--clients both --desktop`.
> Attaching is additive, so never detach a client I did not name.
>
> Rules: use the production router home only, never a `--home` under /tmp
> (the installer refuses scratch homes unless ROUTER_LIVE_RUN=1, and that
> flag is only for deliberate live runs). Never print keys, setup
> URLs, or config bodies. Restarting Codex or Claude Code afterwards is my
> decision, not yours.

After setup, updates are automatic every 4 hours from the public token-free
feed. No GitHub account or repo access is needed, now or ever.
