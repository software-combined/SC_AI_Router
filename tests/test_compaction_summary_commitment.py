"""Commitment boundaries for bounded external compaction summaries."""
import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_router import (availability, compaction_summary, provider_defs,
                       providers)


def _row(slug):
    levels = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh') \
        if slug.startswith('xiaomi/') else ('low', 'high', 'max')
    return SimpleNamespace(slug=slug, provider='openrouter',
                           max_output_tokens=100000, reasoning=levels,
                           provider_prefs=None, upstream_id=slug)


def _payload(model):
    return {'model': model, 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': 'complete'}]}]}


class Response:
    status = 200

    def __init__(self, payload):
        self.body = io.BytesIO(json.dumps(payload).encode())

    def read(self, *args):
        return self.body.read(*args)


class SummaryCommitmentTests(unittest.TestCase):
    def setUp(self):
        rows = {slug: _row(slug)
                for slug in compaction_summary.SUMMARY_MODEL_SLUGS}
        self.enterContext(mock.patch.object(
            providers, 'by_slug', side_effect=lambda slug: rows.get(slug)))
        self.snapshot = {
            'key': availability.key_fingerprint('key'),
            'region': 'global',
            'models': frozenset(compaction_summary.SUMMARY_MODEL_SLUGS),
        }

    def test_summary_requests_require_identity_response_encoding(self):
        sent = []

        class Connection:
            sock = None

            def __init__(self, *args, **kwargs):
                pass

            def connect(self):
                pass

            def request(self, method, path, body=None, headers=None):
                sent.append(headers)

            def getresponse(self):
                model = compaction_summary.SUMMARY_MODEL_SLUGS[0]
                return Response(_payload(model))

            def close(self):
                pass

        with mock.patch.object(compaction_summary.http.client,
                               'HTTPSConnection', Connection):
            result = providers.ExternalResponsesProvider(
                provider_defs.OPENROUTER).summarize(
                    'z-ai/glm-5.3', 'key',
                    [{'type': 'message', 'role': 'user', 'content': 'marker'}],
                    availability_snapshot=self.snapshot)
        self.assertEqual(result, 'complete')
        self.assertEqual([headers.get('Accept-Encoding') for headers in sent],
                         ['identity'])

    def test_request_timeout_after_dispatch_never_falls_back(self):
        started, finished, sent = threading.Event(), threading.Event(), []

        class FirstConnection:
            sock = None

            def connect(self):
                pass

            def request(self, *args, **kwargs):
                sent.append('first')
                started.set()
                try:
                    threading.Event().wait(1)
                finally:
                    finished.set()

            def getresponse(self):
                raise AssertionError('timed-out request must not read')

            def close(self):
                pass

        created = []

        def connection(*args, **kwargs):
            created.append(len(created) + 1)
            return FirstConnection()

        with mock.patch.object(compaction_summary,
                               'SUMMARY_ATTEMPT_DEADLINE_S', 0.05), \
                mock.patch.object(compaction_summary,
                                  'SUMMARY_TOTAL_DEADLINE_S', 0.1), \
                mock.patch.object(compaction_summary.http.client,
                                  'HTTPSConnection', side_effect=connection):
            with self.assertRaises(TimeoutError):
                providers.ExternalResponsesProvider(
                    provider_defs.OPENROUTER).summarize(
                        'z-ai/glm-5.3', 'key',
                        [{'type': 'message', 'role': 'user',
                          'content': 'marker'}],
                        availability_snapshot=self.snapshot)
        self.assertTrue(started.is_set())
        self.assertEqual(sent, ['first'])
        self.assertEqual(created, [1])
        self.assertTrue(finished.wait(1))


if __name__ == '__main__':
    unittest.main()
