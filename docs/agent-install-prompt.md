# Router install prompt for your agent

Paste this to your coding agent (Codex, Claude Code) after downloading the
router files from the Technology library page. The agent runs everything;
you only supply the feed token and approve restarts.

> Set up the SCG mixed-model router on this machine. The bootstrap files
> (`bootstrap.sh` for macOS/Linux, `bootstrap.ps1` for Windows) are in my
> downloads from the Technology library page. My feed token is:
> `SCG_FEED_TOKEN=<paste the token from the library page here>`
>
> Steps: run the bootstrap for my OS with the token, then verify with the
> installer `--preflight` and `--status` probes against the default home
> and show me the redacted summary. If the OpenRouter key is missing, open
> the local setup page it prints and tell me to paste my key there, never
> ask me for the key in chat. If anything fails, stop and show me the
> exact error, do not retry with different flags.
>
> Rules: use the production router home only, never a `--home` under /tmp
> (the installer refuses scratch homes unless ROUTER_LIVE_RUN=1, and that
> flag is only for deliberate live runs). Never print tokens, keys, setup
> URLs, or config bodies. Restarting Codex or Claude Code afterwards is my
> decision, not yours.

After setup, updates are automatic every 4 hours from the token-gated
feed. No GitHub account or repo access is needed, now or ever.
