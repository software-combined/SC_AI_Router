# Repair an existing Router installation

Run [SCG Router setup and repair](https://hub.softwarecombined.com/install)
once, using the link for your computer. An existing installation selects
**Update or repair**. Finish active work and follow the assistant-close prompt.
Keep the setup window open until it reports the result.

Setup uses the current public release for your saved beta or stable channel.
It keeps your keys, subscription sign-ins, connected assistants and disabled
tools. You do not need to uninstall, sign in for downloads, access GitHub
or enter a working key again. Platform scripts remain available when native
installers have not been published.

Version **1.2.6.174** can refuse downloads before contacting the public service.
Publishing another release cannot reach that installation. Start this one
repair action outside its old updater. Public downloads ignore saved legacy
download sign-in files; setup leaves those files in place.

After repair, check the running version and send a short reply through your
assistant. Confirm a later scheduled check succeeds during your signed-in
session. A successful installation alone does not prove either result.

Router controls show the running version, latest verified version for your
channel and last successful check. Update, assistant-connection and controls
warnings stay separate from routing health. A failed update remains visible
even if Router can still answer requests.

**Repair now / Later** appears after a blocked update, two consecutive failures
or two missed four-hour intervals plus 15 minutes. A displayed prompt appears
at most once in 24 hours. Choose **Later** to finish active work. If no desktop
dialog is available, the warning stays pending for the next opening of controls.
Automatic checks keep their existing schedule and never force an assistant closed.

If Router reports an assistant connection conflict, retain the installation.
Setup still delivers verified maintenance tools where possible. It preserves
settings whose ownership it cannot prove. A maintainer can request the
[redacted ownership report](operations.md#uninstall).
Never send raw assistant configuration, keys or subscription credentials.

## Maintainer notice

> If your Router is stuck on an older version or asks you to sign in for
> downloads, run [SCG Router setup and repair](https://hub.softwarecombined.com/install)
> once. Choose your computer and follow the update or repair steps. You do
> not need to uninstall or enter your working key again. Finish active work
> before continuing. Send a short reply afterwards and check the version.

Distribute the notice to known affected users after publication and anonymous
download verification. Publication alone does not establish fleet recovery.

## Verification record, 19 October 2026 AEDT

An isolated profile started with the exact published `1.2.6.174` bundle and
303 matching manifest files. Its signed-out legacy state reproduced the local
download refusal before HTTP. Current setup repaired it to candidate build
`1.3.2.900000`, preserving settings, key, beta selection and legacy auth files.
Runtime health and a later applying update check passed without download sign-in.
The stable Linux launcher selected the retained controller after rollback.
The service manager was simulated; the later check was invoked directly.
This does not prove a physical scheduler or Brent's signed-in session.

Claude Code `2.1.283` completed two bounded synthetic file Read/reply runs through
the recovered runtime. The first did not retain upstream counts. The final run
retained two physical sends reporting `deepseek/deepseek-v4.1-flash-1017`.
Low effort was requested; served effort was not exposed. The probe allowed
three client turns, 2,048 output tokens per call and a USD 0.10 budget per run.
These are retained client/provider reports, not independent model attestation.
Live Router and assistant settings were unchanged.

Codex desktop `26.1013.31256` (`20586`), bundled CLI `0.163.0-alpha.10.2` and
Claude Code versions still match the 17 October compatibility checks. Inference
paths are unchanged, so those paid checks remain applicable. Physical desktop
acceptance and Brent's repair, real reply and later scheduled check remain pending.
Native first-install publication flags remain unchanged.

The unchanged paid client matrix is recorded in [compatibility](compatibility.md).
