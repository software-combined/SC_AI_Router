# Media generation

Codex can generate, display and save images through OpenRouter without a
ChatGPT sign-in. Use router 1.0.13 or later with an OpenRouter-only setup or
the Switch Codex helper. A subscription profile keeps its native image route.

1. Install the update and restart Codex.
2. If your setup uses a ChatGPT subscription, open **Switch Codex** first.
3. Select an image-capable OpenRouter chat model, such as DeepSeek V4.1 Flash.
4. Ask Codex to generate an image. Its image tool uses GPT Image 2 and bills
   your OpenRouter key.

The company model allowlist and the key's model availability still apply.
External image editing remains unavailable and is refused before a send.
Image and video models are not general chat models or extra picker rows.

Video rows submit a job and return its polling URL. Polling and downloading
require the OpenRouter key. The router does not poll automatically. Media
rows remain unlisted previews; video completion and download remain unfinished.

## Client and billing contract

Codex's native image tool sends a separate `/images/generations` request.
A Responses image result does not display an image on Codex 0.160.1.
The router therefore serves that native Images entry point.

Codex 0.160.1 requires its image feature, an image-capable chat model and a
compatible provider profile. The managed external profile supplies the
client's gateway capability header, `x-openai-actor-authorization`, using the
per-install local route token. This credential targets only the local router;
fresh external headers remove it before any OpenRouter send. The profile
keeps `requires_openai_auth = false` and needs no ChatGPT account or auth file.
Both external profiles mark their requests as routed. Changing install mode
therefore cannot send an open external profile's credential to a subscription.

Subscription profiles keep bare image IDs on OpenAI. External-only and
switched profiles resolve the same ID against approved image rows and use the
OpenRouter key. An explicit external registry slug selects that provider in
either mode. Serving identity comes only from the original provider response
or headers; generated client envelopes do not certify the requested model.

## Verification

Verify both normal client configurations without paid calls:

```sh
python3.14 tools/probe_media_generation.py --model openai/gpt-image-2
python3.14 tools/probe_media_generation.py --model openai/gpt-image-2 --variant switched
python3.14 tools/probe_media_generation.py --model google/veo-3.1-fast
```

Add `--live` for one authorized paid generation. Add `--live-chat` to an image
probe to verify real chat orchestration too. Use `--output /absolute/new.png`
to retain its saved image; an existing destination stops the probe before any
paid call. The probe uses the normal installer configuration builder in a
private temporary home and verifies that no ChatGPT account is present.
It does not change installed settings.

Each probe permits one generation and no polls or retries, with a 180-second
client deadline. Media input is capped at 128 KiB. Images use one low-quality
1024-square output; videos use four seconds at 720p without audio. Synthetic
image orchestration permits two chat replies. Live orchestration permits at
most three chat sends with 2,048 output tokens each. Chat input is capped at
8 MiB because the native tool returns its generated PNG to the chat model.

## Agent 57 boundary

SCG Technology owns the deterministic adapter and managed client profile.
They enable Codex's existing image tool and add no agent, loop, tool authority
or filesystem writer. The request boundary is a T0 one-shot generation;
Codex owns artifact storage. Inputs are a registered model and text prompt.
Outputs are image bytes or a video job. Runtime credentials stay outside
model context and request logs. The local token, provider definitions,
company allowlist, key availability, request ceiling and shared transport
timeout guard each send. The existing installer receipt and rollback own
reversible client configuration changes.

External media requests permit one upstream send. Chat repair and replay do
not apply. Malformed required output fails before response headers. Existing
client retries remain the client's responsibility; this adapter adds none.
Persistent writer coordination, consequential-send approval and broad-autonomy
controls are N/A: the adapter performs no such actions. Reassess them if it
gains persistence, background polling, publication or autonomous tool execution.
No runtime-specific Agent 57 adapter exists for this deterministic Python
router; the repository's protocol and transport contracts own exact wiring.
