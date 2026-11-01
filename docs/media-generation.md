# Media generation

With router 1.0.15, images follow the originating chat's provider connection.
An OpenAI subscription chat keeps native OpenAI images. An OpenRouter chat
uses OpenRouter images, including when both chats share one subscription
profile. The conversation model stays selected; the image model is separate.

1. Install the update and restart Codex.
2. Select an image-capable conversation model.
3. Ask Codex to generate an image. Its native tool uses GPT Image 2 on that
   chat's connection. An OpenRouter chat bills the OpenRouter key, not the
   ChatGPT subscription, regardless of the model vendor's name.

The company model allowlist and the key's model availability still apply.
External edits translate one to five inline images into OpenRouter reference
images. OpenAI file IDs cannot cross providers and are refused before a send.
Image and video models are not general chat models or extra picker rows.

Codex has no native video tool in the tested build. The command below is an
explicit fallback, not a native video integration. Existing Responses video
rows still submit a job; the command can resume it and save the completed MP4.
Media rows remain unlisted previews.

## Command fallback

Run from a router release directory or repository checkout. Supply the current
conversation model, not an image or video model, as `--chat-model`:

```sh
python3.14 -m ai_router.media_cli image --chat-model openai/gpt-6-luna --prompt 'A red square' --output /absolute/new.png
python3.14 -m ai_router.media_cli video --chat-model openai/gpt-6-luna --prompt 'A red square slowly turning' --output /absolute/new.mp4
python3.14 -m ai_router.media_cli video --chat-model openai/gpt-6-luna --job-id YOUR_JOB_ID --output /absolute/new.mp4
```

Images default to `openai/gpt-image-2`; videos default to `google/veo-3.1-fast`.
Use `--model` for another approved media model on the same provider.
The command refuses native OpenAI chats rather than billing another provider.
Use Codex's native image tool for those chats; native video is unavailable.

Each invocation sends at most one generation request. Images use one
low-quality, 1024-square PNG. Videos default to four seconds at 720p without
audio; `--duration` permits four, six or eight seconds. Polling permits at
most 20 reads, 30 seconds apart, followed by one download capped at 128 MiB.
Each network operation has the shared socket timeout; the polling interval
is not a whole-run deadline. An existing destination is never overwritten.

The command prints a validated job ID to standard error immediately after
acceptance. If polling or saving fails, retain that ID and use `--job-id`.
Use a new output path for recovery. Failed reserved files remain in place;
the command never deletes a path that another writer could have replaced.
Before reporting success, it checks that the path still names its reserved file.
Resume sends no generation request. Poll and download paths come from the
configured provider, never URLs in the job response. Prompts and keys are
not logged. Standard output names the completed local file only after saving.

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

Codex supplies the originating turn ID with its image request. The router
retains at most 1,024 content-free turn bindings for one hour, in memory only.
Each binding captures the prepared connection and its model-registry snapshot.
Recovered native chats retain their admitted connection without re-reading
stale model membership. The current subscription mode still applies.
Concurrent chats do not share a last-active model. Missing, expired or
conflicting turn IDs fail before generation; the router never silently changes
providers. Restarting the router requires a new chat turn before its image tool.

Explicit API callers can supply `chat_model` when no native turn ID exists.
It cannot override a conflicting turn binding. A media model must belong to
that connection and satisfy the current company allowlist and key availability.
Standalone calls with neither turn ID nor `chat_model` retain the previous
install/profile selection for compatibility; they do not claim chat provenance.
Serving identity comes only from the original provider response or headers;
generated client envelopes do not certify the requested model.

OpenAI's public API uses `/v1/images/generations` and `/v1/images/edits`.
Codex subscription requests use its existing authenticated backend paths,
not the public API-key endpoint. OpenRouter uses `/api/v1/images` for both
generation and reference-image editing. See the [OpenAI Images reference](https://developers.openai.com/api/reference/resources/images)
and [OpenRouter image guide](https://openrouter.ai/docs/guides/overview/multimodal/image-generation).

## Verification

Verify both normal client configurations without paid calls:

```sh
python3.14 tools/probe_media_generation.py --model openai/gpt-image-2
python3.14 tools/probe_media_generation.py --model openai/gpt-image-2 --variant switched
python3.14 tools/probe_media_generation.py --model openai/gpt-image-2 --variant subscription
python3.14 tools/probe_media_generation.py --model google/veo-3.1-fast
```

Add `--live` for one authorized paid generation. Add `--live-chat` to an image
probe to verify real chat orchestration too. Use `--output /absolute/new.png`
to retain its saved image; an existing destination stops the probe before any
paid call. The probe uses the normal installer configuration builder in a
private temporary home. External variants verify that no ChatGPT account is present.
It does not change installed settings. The subscription variant permits
synthetic images only and copies the current login into its temporary home;
it sends no request to a real image or chat provider.

Each probe permits one generation and no polls or retries, with a 180-second
client deadline. Media input is capped at 128 KiB. Images use one low-quality
1024-square output; videos use four seconds at 720p without audio. Synthetic
image orchestration permits two chat replies. Live orchestration permits at
most three chat sends with 2,048 output tokens each. Chat input is capped at
8 MiB because the native tool returns its generated PNG to the chat model.

## Agent 57 boundary

SCG Technology owns the deterministic adapter and managed client profile.
They enable Codex's existing image tool and add no agent or model-selected
tool authority. The request boundary is a T0 one-shot generation; Codex owns
native image storage. The explicit command adds bounded video polling and
writes only its caller-selected, new output file. Inputs are a registered model
and text prompt. Outputs are image bytes, a video job or the saved result.
Runtime credentials stay outside
model context and request logs. The local token, provider definitions,
company allowlist, key availability, request ceiling and shared transport
timeout guard each send. The existing installer receipt and rollback own
reversible client configuration changes.

External media requests permit one upstream send. Chat repair and replay do
not apply. Malformed required output fails before response headers. Existing
client retries remain the client's responsibility; this adapter adds none.
Turn bindings are transient and hold no user content. The command's exclusive
file creation and recovery receipt protect paid work and existing files.
Background polling, publication and broad autonomy remain out of scope.
No runtime-specific Agent 57 adapter exists for this deterministic Python
router; the repository's protocol and transport contracts own exact wiring.
