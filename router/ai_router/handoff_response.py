"""Native handoff marking with bounded, content-free wire provenance."""
import json
import re

from . import agent_handoffs as handoffs, errors, events, request_evidence, sse, transport

MAX_CALLS = 32
MAX_OBSERVATIONS = 3 * MAX_CALLS  # added, done and completed for each call


def _shape(item):
    namespace = {handoffs.NATIVE_NAMESPACE: 'native', handoffs.PLAINTEXT_NAMESPACE: 'plaintext'}.get(
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

    def observe(self, before, client, size, marker_rejected=False, guard_rejected=False):
        self.offset += size
        try:
            self._observe(before, client, marker_rejected, guard_rejected)
        except Exception:
            self._limit()

    def _observe(self, before, client, marker_rejected, guard_rejected):
        phase, original = _items(before)
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
            end = final[index] if index < len(final) else None
            self._emit('handoff_observed', call_ordinal=ordinal, phase=phase, tool=item['name'],
                       declaration=getattr(self.names, 'location', 'unknown'),
                       schema_mode='readable' if item['name'] in self.names else 'native',
                       message_shape=handoffs.message_shape(item),
                       identity_consistent=consistent, envelope_changed=call['changed'],
                       upstream=upstream, client=_shape(end) if isinstance(end, dict) else None,
                       marker_rejected=marker_rejected, guard_rejected=guard_rejected,
                       frame_end_offset=None if marker_rejected or guard_rejected else self.offset)

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


def _mark_output(response, names):
    output = response.get('output')
    if not isinstance(output, list):
        return response
    marked = [handoffs.mark_readable(item, names) for item in output]
    return response if all(a is b for a, b in zip(output, marked)) else {**response, 'output': marked}


def _mark(document, names, stream):
    """Mark readable calls in one event or JSON body; an unchanged document keeps its bytes."""
    if not stream:
        return _mark_output(document, names)
    marked = document
    if document.get('type') in ('response.output_item.added', 'response.output_item.done'):
        item = document.get('item')
        if isinstance(item, dict) and (new := handoffs.mark_readable(item, names)) is not item:
            marked = {**marked, 'item': new}
    response = document.get('response')
    if isinstance(response, dict) and (new := _mark_output(response, names)) is not response:
        marked = {**marked, 'response': new}
    return marked


def _map(document, names, trace, original, stream):
    try:
        marked = _mark(document, names, stream)
    except errors.ResponseRejected:
        trace.observe(document, None, 0, marker_rejected=True)
        raise
    try:
        for item in _items(marked)[1]:
            handoffs.validate_handoff(item, names)
    except errors.ResponseRejected:
        trace.observe(document, None, 0, guard_rejected=True)
        raise
    wire = (sse.replace_data(original, json.dumps(marked).encode()) if stream
            else json.dumps(marked).encode()) if marked is not document else original
    trace.observe(document, marked, len(wire))
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
