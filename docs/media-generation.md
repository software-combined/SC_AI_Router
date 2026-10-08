# Media generation

Codex's image tool sends a separate Images request. A Responses image result
does not display an image on Codex 0.160.1. The router therefore serves the
native `/images/generations` entry point.

Codex 0.160.1 exposes this tool only with its image feature, a vision-capable
chat model and a compatible signed-in provider profile. The stock external-only
router profile does not enable the tool. The isolated probe supplies that
profile; this preview does not change installed client settings.

Subscription mode keeps bare image model IDs on OpenAI. External-only mode
resolves the same ID against approved image rows and uses the external key.
An explicit external registry slug selects that provider in either mode.
The company allowlist and key-scoped availability gate still apply.
External image editing is outside this first slice and is refused before a send.
Serving identity comes only from the original provider response or headers;
generated client envelopes never certify the requested model.

Video rows submit a job and return its polling URL. Polling and downloading
require the OpenRouter key. The router does not poll automatically. Media
rows remain unlisted previews; they are not general chat models.

Verify the real client without paid calls:

```sh
python3.14 tools/probe_media_generation.py --model openai/gpt-image-2
python3.14 tools/probe_media_generation.py --model google/veo-3.1-fast
```

Add `--live` for the authorized paid check. Each probe permits one generation,
no polls, a 180-second client deadline and a bounded request. Images use one
low-quality output; videos use four seconds at 720p without audio.

## Agent 57 boundary

SCG Technology owns the deterministic adapter. It extends Codex's existing
image tool and adds no agent, loop, tool authority or filesystem writer.
The request boundary is a T0 one-shot generation; Codex owns artifact storage.
Inputs are a registered model and text prompt. Outputs are image bytes or a
video job. Runtime credentials stay outside model context and request logs.
The loopback token, provider definitions, company allowlist, key availability,
request-size ceiling and shared transport timeout guard each send.

External media requests permit one upstream send. Chat repair and replay do
not apply. Malformed required output fails before response headers. Existing
client retries remain the client's responsibility; this adapter adds none.
Persistent writer coordination, consequential-send approval and broad-autonomy
controls are N/A: the adapter performs no such actions. Reassess them if it
gains persistence, background polling, publication or autonomous tool execution.
No runtime-specific Agent 57 adapter exists for this deterministic Python
router; the repository's protocol and transport contracts own exact wiring.
