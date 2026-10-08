"""Provider adapters. Each owns model membership, request preparation, upstream target and response adaptation."""
import json
import time
from . import (availability, compaction as comp, local_services, handoff_response,
               media, provider_defs, request_context, transport, turn_budget, jev_compaction)
from . import outbound, rejected_repair, request_evidence, subscription_roster
from .compaction_summary import (summary_entries as _summary_entries,
                                 summarize as _summarize)
from .errors import PreparationError, SubscriptionRequired, UnknownModel
from .registry import by_slug, near_miss, upstream_id_for
from .events import log_event
from .discovered import remember
from .tool_adapter import snoop_response_identity, stream_events, ToolEvents

from .transport import HOP_HEADERS, Prepared, passthrough
NATIVE_SERVICE_PATHS = {'/alpha/search', '/alpha/notes/v2/thread_hint', '/guardian', '/guardian-classifier'}


def is_native_service(path):
    # Any native path the subscription definitions claim (prefix rule).
    return provider_defs.native_service_path(path)
# router.py guards compaction with this name; the external stages use the same rule.
reject_opaque_agent_items = outbound.contain


class SubscriptionProvider:
    """The client's own ChatGPT login; the router holds no credential."""

    def __init__(self):
        self.defn = provider_defs.OPENAI
        self.name = self.defn.id
        self.host = self.defn.host
        self.kind = self.defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        del allowed  # Subscription rows are never allowlisted.
        if openai_mode == 'none':
            return False
        if is_native_service(path):
            return True
        entry = catalogue.get(model) if isinstance(model, str) else None
        if entry is not None:
            return entry.provider == provider_defs.OPENAI.id
        return isinstance(model, str) and (model in openai_models or model in subscription_roster.HELPER_SLUGS)

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None, context=None):
        # The URL path token is the loopback auth; Codex >=0.153.4 omits the
        # subscription Authorization header, so forward client headers unchanged.
        fwd = {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}
        # Readable briefs only where an external child can exist: an external key
        # resolves. A credentials object without that lookup keeps the stock contract.
        missing = getattr(credentials, 'key_missing', None)
        readable = path == '/responses' and missing is not None and any(
            missing(defn.id) is None for defn in provider_defs.external_defs())
        payload, names, changed = outbound.project_subscription(
            payload, path, catalogue=context.catalogue if context is not None else None,
            readable=readable)
        if changed:
            fwd = {k: v for k, v in fwd.items() if k.lower() not in ('content-encoding', 'accept-encoding')}
            fwd['Accept-Encoding'] = 'identity'
            raw_body = json.dumps(payload).encode()
            decoded_len = len(raw_body)  # the only size a rewrite carries
        return Prepared(self.host, self.defn.path_for(provider_defs.RESPONSES, path), fwd,
                        raw_body, names, self.name, context=context, decoded_body_bytes=decoded_len)

    def adapt(self, response, tool_names, notes=None):
        if tool_names and response.status == 200:
            yield from handoff_response.adapt_response(response, tool_names, notes)
        elif notes is not None and response.status == 200:
            yield from snoop_response_identity(response, notes)
        else:
            yield from passthrough(response)

    def repair_rejected(self, prepared, described, raw):
        return rejected_repair.encrypted_content(prepared, described, raw)


class ExternalResponsesProvider:
    """One external provider serving the Codex Responses family (Plan 141)."""

    def __init__(self, defn, region='global'):
        self.defn = defn
        self.name = defn.id
        self.region = region if provider_defs.valid_region(region) else 'global'
        self.host = provider_defs.region_host(defn.id, self.region) or defn.host
        self.kind = defn.kind

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        entry = catalogue.get(model) if isinstance(model, str) else None
        if (entry is None or entry.provider != self.defn.id
                or is_native_service(path)):
            return False
        # Plan 068 allowlist plus the key-filtered snapshot gate
        # routing like the picker; no snapshot yet means policy decides.
        if allowed is not None and model not in allowed:
            return False
        from . import availability as _availability
        return _availability.permitted(model)

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None, context=None):
        if path not in ('/responses', '/responses/compact'):
            raise PreparationError(f'{self.defn.label} supports responses only')
        # Every model fact below reads this row: routed, the ingress snapshot (Plan 188).
        entry = context.row if context is not None else by_slug(model) if isinstance(model, str) else model
        media_kind = getattr(entry, 'media_kind', None)
        if media_kind is not None and path == '/responses':
            kind, tool = media.media_tool(payload)
            if kind != media_kind or tool is None:
                raise PreparationError(
                    f'{model} needs a {media_kind}-generation tool entry')
            upstream_id = ((upstream_id_for(entry) if entry is not None else None)
                           or (model if isinstance(model, str) else ''))
            return media.prepared(self, kind, tool, model, entry, payload,
                                  upstream_id, credentials, context)
        if media.media_tool(payload)[0] is not None:
            raise PreparationError(f'{model} is not a media-generation model')
        # Before any rewrite: what this client's thread carries. The slim below
        # is invisible upstream, so provider usage alone never moves the trigger.
        carried = turn_budget.carried_tokens(payload, decoded_len) if decoded_len else None
        payload, tool_names = outbound.project_external(
            payload, path, model, entry, catalogue=context.catalogue if context is not None else None)
        cap = payload['max_output_tokens']
        window = getattr(entry, 'context_window', 0) or 0
        carried = min(carried, window) if carried and window else carried
        # Context size stays the provider's call: a chars-per-token estimate
        # refused long turns the client still had room for.
        headers = dict(self.defn.request_headers)
        headers.update({'Authorization': 'Bearer ' + credentials.key_for(self.defn.id),
                        'Content-Type': 'application/json',
                        'Accept-Encoding': 'identity'})
        body = json.dumps(payload).encode()
        if len(body) > turn_budget.BODY_BUDGET:
            payload, stats = turn_budget.fit(payload, turn_budget.BODY_BUDGET, len(body))
            if stats:
                body = json.dumps(payload).encode()
                log_event('turn_trimmed', model=model, prepared_bytes=len(body), **stats)
        return Prepared(self.host, self.defn.path_for(provider_defs.RESPONSES, '/responses'),
                        headers, body, tool_names, self.name, output_cap=cap,
                        context_tokens=carried, context=context, decoded_body_bytes=len(body))

    def adapt(self, response, tool_names, notes=None):
        # Media turns mark their tool names with a 'media:<kind>' tuple;
        # chat turns carry the ToolNames map, which never equals one.
        if response.status == 200 and media.is_media_tools(tool_names):
            yield from media.adapt(response, tool_names)
            return
        if notes is not None and not tool_names and response.status == 200:
            yield from snoop_response_identity(response, notes)
        elif tool_names and response.status == 200:
            if 'text/event-stream' in response.getheader('Content-Type', ''):
                yield from stream_events(response, tool_names, notes)
            else:
                result = json.loads(transport.read_capped(response, transport.MAX_UPSTREAM_BODY))
                request_evidence.observe(notes, result, 'response')
                if notes is not None and (model := request_evidence.identifier(result.get('model'))):
                    notes['served_model'] = model
                adapter = ToolEvents(tool_names, notes)
                result['output'] = [adapter.item(item) for item in result.get('output', [])]
                turn_budget.report_usage(result.get('usage'), notes)
                yield json.dumps(result).encode()
        else:
            yield from passthrough(response)

    def repair_rejected(self, prepared, described, raw):
        return rejected_repair.annotation_strip(self.defn, prepared, described, raw)

    def _summary_snapshot(self, key):
        snap = availability.current()
        return snap if (snap is not None
                        and snap.get('key') == availability.key_fingerprint(key)
                        and snap.get('region') == self.region) else None

    def _jev_enabled(self):
        return self.region == 'global' and jev_compaction.state() != 'off'

    def _require_summary_rows(self, key, context, allowed):
        snapshot = self._summary_snapshot(key)
        if snapshot is None:
            raise ValueError('Compaction summary models unavailable')
        entries = _summary_entries(
            self.defn.id, None if context is None else context.catalogue,
            allowed, snapshot, by_slug)
        if not entries:
            raise ValueError('Compaction summary models unavailable')
        return snapshot

    def _summary_for_compaction(self, model, key, items, row, context, allowed):
        summary_snapshot = self._require_summary_rows(key, context, allowed)
        use_jev = self._jev_enabled()
        return (
            (jev_compaction.summary(model, key, items, self.defn, row=row)
             if use_jev else None)
            or self.summarize(model, key, items, row, context, allowed,
                              summary_snapshot)
        )

    def compact(self, model, payload, key, row=None, context=None, allowed=None):
        try:
            items = payload.get('input', [])
            kinds, shapes = {}, {}
            for _item in items if isinstance(items, list) else []:
                kind = _item.get('type') if isinstance(_item, dict) else '?'
                kinds[kind] = kinds.get(kind, 0) + 1
                if isinstance(_item, dict):
                    shapes.setdefault(kind, set()).update(_item.keys())
            log_event('compact_started', active_model=model,
                      input_items=len(items) if isinstance(items, list) else -1,
                      item_kinds=kinds,
                      item_keys={k: sorted(v) for k, v in shapes.items()})
            users = comp.extract_user_messages(items)
            if not users:
                raise ValueError('No user messages to compact')
            summary = self._summary_for_compaction(
                model, key, items, row, context, allowed)
            log_event('compact_summarized', active_model=model,
                      summary_chars=len(summary))
            output = comp.build_compact_v1_output(users, summary)
            remember(items, summary)
            return output
        except ValueError as exc:
            raise PreparationError(str(exc))

    def compact_trigger(self, model, payload, key, row=None, context=None,
                        allowed=None):
        """Answer a V2 trigger inline with exactly one ocx1 compaction item."""
        try:
            items = [item for item in payload.get('input', [])
                     if not (isinstance(item, dict)
                             and item.get('type') == comp.TRIGGER_TYPE)]
            users = comp.extract_user_messages(items)
            if not users:
                raise ValueError('No user messages to compact')
            summary = self._summary_for_compaction(
                model, key, items, row, context, allowed)
            log_event('compact_triggered', active_model=model,
                      summary_chars=len(summary))
            remember(items, summary)
            return [comp.v2_compaction_item(summary)]
        except ValueError as exc:
            raise PreparationError(str(exc))

    def summarize(self, model, key, payload_items, row=None, context=None,
                  allowed=None, availability_snapshot=None):
        """Summarize through the pinned fast rows; `model`/`row` identify the request."""
        del row
        snapshot = (self._summary_snapshot(key)
                    if availability_snapshot is None else availability_snapshot)
        if snapshot is None:
            raise ValueError('Compaction summary models unavailable')
        return _summarize(self, key, payload_items,
                          catalogue=None if context is None else context.catalogue,
                          allowed=allowed, active_model=model, lookup=by_slug,
                          log=log_event, monotonic=time.monotonic,
                          availability_snapshot=snapshot)


class LocalServicesProvider:
    name = 'local-services'
    host = None
    kind = 'local'
    defn = None

    def owns(self, model, path, openai_models, openai_mode='subscription',
             allowed=None, *, catalogue):
        del allowed, catalogue  # Native service paths are never allowlisted.
        return openai_mode == 'none' and is_native_service(path)

    def prepare(self, model, path, payload, raw_body, headers, credentials, decoded_len=None, context=None):
        del decoded_len, context  # This adapter answers locally; nothing is carried.
        local_services.answer(path)
        raise AssertionError('unreachable')

    def adapt(self, response, tool_names):
        raise AssertionError('unreachable')


def adapters(region='global'):
    """One adapter per external def serving Responses, plus the rest.

    `region` selects the endpoint profile host (Plan 145); unknown
    names fall back to the global host inside the adapter.
    """
    return (tuple(ExternalResponsesProvider(defn, region)
                  for defn in provider_defs.external_serving(provider_defs.RESPONSES))
            + (SubscriptionProvider(), LocalServicesProvider()))


def compaction_call(provider, model, path, payload, row=None, context=None,
                    allowed=None):
    """Bound local serve for external compact/V2-trigger turns, else None."""
    if provider.kind != provider_defs.EXTERNAL:
        return None
    row = context.row if context is not None else row
    if path == '/responses/compact':
        return lambda key: provider.compact(
            model, payload, key, row, context=context, allowed=allowed)
    if path == '/responses' and comp.has_compaction_trigger(payload.get('input', [])):
        return lambda key: provider.compact_trigger(
            model, payload, key, row, context=context, allowed=allowed)
    return None


def select(model, path, openai_models=(), openai_mode='subscription',
           region='global', allowed=None, catalogue=None):
    allowset = None if allowed is None else frozenset(allowed)
    rows = request_context.capture() if catalogue is None else catalogue
    for provider in adapters(region):
        if provider.owns(model, path, openai_models, openai_mode,
                         allowed=allowset, catalogue=rows):
            return provider
    if openai_mode == 'none' and isinstance(model, str) and model in (openai_models or []):
        raise SubscriptionRequired()
    entry = rows.get(model) if isinstance(model, str) else None
    defn = provider_defs.get(entry.provider) if entry is not None else None
    if defn is not None and not defn.serves(provider_defs.RESPONSES):
        raise PreparationError(
            f'{defn.label} models are available to Claude Code only: '
            f'{entry.slug} does not serve the Codex Responses API')
    guess = near_miss(model, rows)
    if guess is not None and allowset is not None and guess not in allowset:
        guess = None  # never disclose a slug the portco policy excludes
    raise UnknownModel(model if isinstance(model, str) else None,
                       (guess,) if guess else ())
