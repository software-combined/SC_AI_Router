"""Native handoff adaptation with bounded, content-free wire provenance."""
import json
import re

from . import agent_handoffs as handoffs, errors, events, request_evidence, sse, transport

MAX_CALLS = 32
MAX_OBSERVATIONS = 3 * MAX_CALLS  # added, done and completed for each call


def _shape(item):
    namespace = {'collaboration': 'native', 'collaboration_plaintext': 'plaintext'}.get(
        item.get('namespace'), 'other')
    marker = item.get('encrypted_function_args')
    marker = ('absent' if 'encrypted_function_args' not in item else 'empty' if marker == []
              else 'nonempty' if isinstance(marker, list) else 'invalid')
    arguments = item.get('arguments')
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return {'namespace': namespace, 'marker': marker, 'arguments': 'invalid'}
    kind = {dict: 'object', list: 'array', str: 'string', bool: 'boolean',
            int: 'number', float: 'number', type(None): 'null'}.get(type(arguments), 'other')
    return {'namespace': namespace, 'marker': marker, 'arguments': kind}


def _items(document):
    if not isinstance(document, dict):
        return 'absent', []
    kind = document.get('type')
    if kind in ('response.output_item.added', 'response.output_item.done'):
        return kind.rsplit('.', 1)[-1], [document.get('item')]
    response = document.get('response', document)
    output = response.get('output') if isinstance(response, dict) else None
    phase = 'json' if 'type' not in document else 'completed' if kind == 'response.completed' else 'other'
    return phase, output if isinstance(output, list) else []


class Trace:
    """Observe decisions without granting plaintext authority or retaining content."""

    def __init__(self, names, notes):
        self.names, self.notes = names, notes
        self.calls, self.identities = [], {}
        self.observations = self.offset = 0
        self.incomplete = False
        notes = notes or {}
        request = notes.get('request_id')
        self.context = {'request_id': request if isinstance(request, str)
                        and re.fullmatch(r'[0-9a-f]{32}', request) else None,
                        'attempt': notes.get('attempt') if type(notes.get('attempt')) is int else None}

    def _emit(self, event, **fields):
        try:
            events.log_event(event, **self.context, **fields)
        except Exception:
            self.incomplete = True  # A logging failure never changes the wire.

    def _limit(self):
        if not self.incomplete:
            self._emit('handoff_observation_limited', observations=self.observations,
                       calls=len(self.calls), incomplete=True)
        self.incomplete = True

    def _call(self, item):
        keys = {(field, item[field]) for field in ('id', 'call_id')
                if isinstance(item.get(field), str) and 0 < len(item[field]) <= 256}
        found = {self.identities[key] for key in keys if key in self.identities}
        if found:
            ordinal = min(found)
            call = self.calls[ordinal]
            consistent = len(found) == 1 and keys == call['keys']
        else:
            if len(self.calls) >= MAX_CALLS:
                self._limit()
                return None, None, False
            ordinal = len(self.calls)
            call = {'keys': keys, 'phases': set(), 'first': None, 'changed': False}
            self.calls.append(call)
            for key in keys:
                self.identities[key] = ordinal
            consistent = bool(keys)
        return ordinal + 1, call, consistent

    def observe(self, before, restored, client, size, rejected=False, guard_rejected=False):
        self.offset += size
        try:
            self._observe(before, restored, client, rejected, guard_rejected)
        except Exception:
            self._limit()

    def _observe(self, before, restored, client, rejected, guard_rejected):
        phase, original = _items(before)
        _, middle = _items(restored)
        _, final = _items(client)
        for index, item in enumerate(original):
            if (not isinstance(item, dict) or item.get('type') != 'function_call'
                    or item.get('name') not in handoffs.HANDOFF_TOOLS):
                continue
            if self.observations >= MAX_OBSERVATIONS:
                self._limit()
                return
            ordinal, call, consistent = self._call(item)
            if call is None:
                return
            self.observations += 1
            call['phases'].add(phase)
            upstream = _shape(item)
            state = (upstream['namespace'], upstream['marker'])
            if call['first'] is None:
                call['first'] = state
            call['changed'] |= call['first'] != state
            mid = middle[index] if index < len(middle) else None
            end = final[index] if index < len(final) else None
            self._emit('handoff_observed', call_ordinal=ordinal, phase=phase,
                       tool=item['name'], alias_advertised=item['name'] in self.names,
                       declaration=getattr(self.names, 'location', 'unknown'),
                       schema_mode='plaintext' if item['name'] in self.names else 'unadvertised',
                       identity_consistent=consistent, envelope_changed=call['changed'],
                       upstream=upstream, restored=_shape(mid) if isinstance(mid, dict) else None,
                       client=_shape(end) if isinstance(end, dict) else None,
                       restoration_rejected=rejected,
                       guard_rejected=guard_rejected,
                       frame_end_offset=None if rejected or guard_rejected else self.offset)

    def finish(self):
        for ordinal, call in enumerate(self.calls, 1):
            expected = {'json'} if 'json' in call['phases'] else {'added', 'done', 'completed'}
            self._emit('handoff_observation_finished', call_ordinal=ordinal,
                       missing_envelopes=sorted(expected - call['phases']),
                       envelope_changed=call['changed'], incomplete=self.incomplete)
        if self.notes is not None and (self.calls or self.incomplete):
            self.notes['handoff_observations'] = self.observations
            self.notes['handoff_observation_incomplete'] = self.incomplete
        self.calls.clear()
        self.identities.clear()


def _map(document, names, trace, original, stream):
    try:
        restored = (handoffs.restore_event(document, names) if stream
                    else handoffs.restore_response(document, names))
    except errors.ResponseRejected:
        trace.observe(document, None, None, 0, rejected=True)
        raise
    try:
        for item in _items(restored)[1]:
            handoffs.validate_handoff(item, names)
    except errors.ResponseRejected:
        trace.observe(document, restored, None, 0, guard_rejected=True)
        raise
    wire = (sse.replace_data(original, json.dumps(restored).encode()) if stream
            else json.dumps(restored).encode()) if restored is not document else original
    trace.observe(document, restored, restored, len(wire))
    return wire


def adapt_response(response, names, notes=None):
    """Preserve the native adapter contract; logs never imply child execution."""
    trace = Trace(names, notes)
    try:
        if not getattr(names, 'stream', False) and 'text/event-stream' not in response.getheader('Content-Type', ''):
            raw = transport.read_capped(response, transport.MAX_UPSTREAM_BODY)
            result = json.loads(raw)
            request_evidence.observe(notes, result, 'response')
            wire = _map(result, names, trace, raw, False)
            if notes is not None and (model := request_evidence.identifier(result.get('model'))):
                notes['served_model'] = model
            yield wire
            return
        for frame, data in sse.blocks(sse.lines(transport.passthrough(response))):
            if not data or data == b'[DONE]':
                trace.offset += len(frame)
                yield frame
                continue
            event = json.loads(data)
            request_evidence.response_event(notes, event)
            wire = _map(event, names, trace, frame, True)
            if event.get('type') == 'response.completed' and notes is not None:
                model = request_evidence.identifier(event.get('response', {}).get('model'))
                if model:
                    notes['served_model'] = model
            yield wire
    finally:
        trace.finish()
