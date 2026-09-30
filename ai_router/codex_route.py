"""The switched Codex route: its header, the local answer on it, and readiness.

Codex desktop 26.917.51856 and later disables Send for every model once the
ChatGPT allowance runs out, but only while its active provider needs OpenAI
sign-in. Switch Codex therefore points Codex at the router through a provider
entry that needs no sign-in and sends `HEADER` with every request. Codex then
sends no ChatGPT credentials, so a ChatGPT subscription turn forwarded as usual
fails upstream, is retried five times, and ends on an error that shows the
router's address. The header marks the route; a missing credential never does.

On that route a ChatGPT request is answered here and nothing is sent. Native
service paths get the no-subscription answers from `local_services`. Every
other request gets one final `invalid_prompt` refusal that names the model's
twin row when this machine's Codex picker lists it. `ingress.error` sends it
to a streaming turn as one `response.failed` frame, whose message Codex
0.153.1 and 0.158 show as sent, and to anything else as a 400; neither
version retries either form, and 0.153.1 shows the 400's whole body.

Helper turns get the same refusal. The helper fallback moves a turn to its
twin only after the subscription refuses it, and this route sends nothing.

`ready` is what Switch Codex asks before it points Codex's picker at the
routed-only list (`routed_models`). The check lives here rather than beside
the list's writer because the availability sync imports that writer, and the
check reads availability back: side by side they would import each other.
"""
from . import (availability, errors, local_services, provider_defs, routed_models,
               subscription_roster)
from .clients import visible_for

HEADER = 'x-scg-codex-route'  # lowercase, as the Switch Codex provider entry sends it


class Refusal(errors.LocalAnswer):
    """One final answer; `stream` asks for a `response.failed` frame."""

    def __init__(self, message, stream, detail=None):
        super().__init__(400, 'invalid_prompt', message, detail)
        self.stream = stream


def switched(headers):
    """True when the request carries `HEADER`, whatever its case."""
    return any(key.lower() == HEADER for key in headers)


def message(twin=None):
    """Refusal wording that names `twin`, a registry row, when there is one."""
    login = provider_defs.OPENAI.subscription_label
    routed = provider_defs.label_for(provider_defs.DEFAULT_EXTERNAL)
    if twin is None:
        subject, pick = 'This model', 'Pick another model'
    else:
        label = provider_defs.label_for(twin.provider)
        # A picker label reads `<Vendor>: <Model> · <Provider>` (AGENTS.md section 8).
        subject = twin.display_name.removesuffix(' · ' + label).removeprefix(twin.vendor + ': ')
        pick = f'Pick "{twin.display_name}" to use it through {label}'
    return (f'{subject} uses your {login}, which is off while Codex is switched to '
            f'{routed} models. {pick}, or open Switch Codex to go back to your {login}.')


def refuse(path, payload, context, twin=None):
    """Raise the local answer for a ChatGPT request on the switched route.

    `twin` is the twin slug this machine may route, already gated by the
    portco allowlist and the key's availability; the answer names it only
    when it is this model's own twin (never the Luna stand-in that answers
    helper turns) and the Codex picker lists its row.
    """
    if provider_defs.native_service_path(path):
        local_services.answer(path)
    own = subscription_roster.TWIN_PREFIX + subscription_roster.SUCCESSORS.get(
        context.slug, context.slug)
    row = context.catalogue.get(twin) if twin == own else None
    if row is not None and not visible_for(row, 'codex'):
        row = None
    raise Refusal(message(row), payload.get('stream') is True,
                  f'switched Codex route: {context.slug}, twin {row.slug if row else None}')


def ready(home):
    """True when the routed-only list has rows the key's current snapshot allows.

    "Current" is the id set the picker merge reads (`availability.effective_ids`
    for the installed key and region). A list that still names a model that
    snapshot no longer allows fails until the next sync rewrites it.
    """
    allowed = availability.effective_ids(
        home, availability.current_key(home), availability.current_region(home))
    listed = routed_models.rows(home)
    return bool(listed) and allowed is not None and all(
        row.get('slug') in allowed for row in listed)
