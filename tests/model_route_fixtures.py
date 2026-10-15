"""Offline route-matrix fixtures; the real handler owns every request."""
import json
import http.client
import threading
from unittest import mock

from ai_router import (outbound, provider_defs, registry, request_context, router,
                       sse, upstream)
from tests.fakes import FakeUpstream, install_fake
from tests.harness import auth_file, post, start_server, test_state

PROTOCOLS = (provider_defs.RESPONSES, provider_defs.MESSAGES)
HEADERS = {'Authorization': 'Bearer subscription-fixture',
           'x-api-key': 'subscription-key-fixture', 'anthropic-beta': 'signed-fixture',
           'chatgpt-account-id': 'account-fixture'}


def routes():
    return tuple((row, protocol) for row in registry.MODELS for protocol in PROTOCOLS
                 if registry.row_serves(row, protocol))


def frame(kind, **fields):
    return sse.frame(json.dumps({'type': kind, **fields}).encode())


def payload(model, protocol, effort='low', stream=True):
    body = {'model': model, 'stream': stream}
    if protocol == provider_defs.RESPONSES:
        body.update(input=[{'role': 'user', 'content': 'synthetic route check'}],
                    reasoning={'effort': effort}, tools=[])
    else:
        body.update(messages=[{'role': 'user', 'content': 'synthetic route check'}],
                    max_tokens=64, tools=[])
    return body


def media_payload(model, kind, stream=False):
    tool = {'type': 'image_generation' if kind == 'image' else 'video_generation'}
    return {'model': model, 'stream': stream,
            'input': [{'role': 'user', 'content': 'synthetic media check'}],
            'reasoning': {'effort': 'none'}, 'tools': [tool]}


def media_success(model, kind):
    if kind == 'image':
        value = {'created': 1748372400, 'model': model,
                 'data': [{'b64_json': 'QUJD', 'media_type': 'image/png'}],
                 'usage': {'total_tokens': 7}}
    else:
        value = {'id': 'job_fixture', 'model': model, 'status': 'pending',
                 'polling_url': 'https://openrouter.ai/api/v1/videos/job_fixture'}
    return FakeUpstream(200, json.dumps(value).encode(),
                        [('Content-Type', 'application/json')])


def success(model, protocol, stream=True):
    if protocol == provider_defs.RESPONSES:
        value = {'model': model, 'status': 'completed', 'output': []}
        wire = (frame('response.created', response={'model': model, 'output': []})
                + frame('response.completed', response=value) if stream
                else json.dumps(value).encode())
    else:
        value = {'id': 'msg_fixture', 'type': 'message', 'role': 'assistant',
                 'model': model, 'content': [], 'stop_reason': 'end_turn'}
        wire = (frame('message_start', message={**value, 'stop_reason': None})
                + frame('message_delta', delta={'stop_reason': 'end_turn'})
                + frame('message_stop') if stream else json.dumps(value).encode())
    return FakeUpstream(200, wire, [('Content-Type',
        'text/event-stream' if stream else 'application/json')])


def overloaded(model, protocol, committed=False):
    if protocol == provider_defs.RESPONSES:
        wire = frame('response.created', response={'model': model, 'output': []})
        if committed:
            wire += frame('response.output_text.delta', delta='synthetic answer')
        wire += frame('response.failed', response={'model': model,
                      'error': {'code': 'overloaded'}})
    else:
        wire = frame('message_start', message={'id': 'msg_fixture', 'type': 'message',
                     'role': 'assistant', 'model': model, 'content': [], 'stop_reason': None})
        if committed:
            wire += frame('content_block_start', index=0, content_block={
                'type': 'tool_use', 'id': 'call_fixture', 'name': 'lookup', 'input': {}})
        wire += frame('error', error={'type': 'overloaded_error'})
    return FakeUpstream(200, wire, [('Content-Type', 'text/event-stream')])


class RouteHarness:
    def __init__(self, test):
        self.test, self.responses = test, iter(())
        self.sends = install_fake(test, lambda: next(self.responses))
        self.closed = test.enterContext(mock.patch.object(
            http.client.HTTPSConnection, 'close', autospec=True))
        state = test_state(auth_file(test))
        state['openai_models'] = ['gpt-6-luna']
        self.server = start_server(state)
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        self.finished = threading.Event()
        finished = self.finished

        class CompletionHandler(router.Handler):
            def do_POST(self):
                try:
                    super().do_POST()
                finally:
                    finished.set()

        self.server.RequestHandlerClass = CompletionHandler

    def turn(self, body, protocol, responses, native=False, sent=True, projected=True):
        self.responses = iter(responses)
        self.sends.clear()
        self.closed.reset_mock()
        self.finished.clear()
        upstream.clear_refusals()
        name = ('project_subscription' if native else 'project_external')
        if protocol == provider_defs.MESSAGES:
            name = 'project_messages_subscription' if native else 'project_messages_external'
        with mock.patch.object(router, 'log_event') as logged, \
                mock.patch.object(request_context, 'resolve', wraps=request_context.resolve) as resolve, \
                mock.patch.object(outbound, name, wraps=getattr(outbound, name)) as project:
            response = post(self.server.server_port,
                            '/test-token' + ('/responses' if protocol == provider_defs.RESPONSES
                                             else '/v1/messages'), body, HEADERS)
            wire, status = response.read(), response.status
            response.close()
            self.test.assertTrue(self.finished.wait(2), 'request cleanup did not finish')
        self.test.assertEqual(self.server.inflight, 0)
        self.test.assertEqual(len({call.args[0] for call in self.closed.call_args_list}),
                              len(self.sends), 'an upstream connection was not closed')
        facts = [c.kwargs for c in logged.call_args_list if c.args[0] == 'attempt_ledger']
        self.test.assertEqual(len(facts), int(sent))
        self.test.assertEqual(resolve.call_count, 1)
        self.test.assertEqual(project.call_count, int(projected))
        self.test.assertNotIn('subscription-fixture', json.dumps(facts))
        return status, wire, list(self.sends), facts[0] if facts else None
