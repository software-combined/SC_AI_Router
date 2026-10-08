"""Media translation: prompt extraction, bodies and answer shapes."""
import json
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from ai_router import availability, catalogue, media, provider_defs, registry
from ai_router.errors import PreparationError
from tests.fakes import FakeUpstream
from tests.model_route_fixtures import RouteHarness, media_payload


class PromptTests(unittest.TestCase):
    def test_last_user_text_wins(self):
        items = [{'role': 'user', 'content': 'first'},
                 {'role': 'assistant', 'content': 'reply'},
                 {'type': 'message', 'role': 'user', 'content': [
                     {'type': 'input_text', 'text': 'draw a cat'}]}]
        self.assertEqual(media.prompt_from_input(items), 'draw a cat')

    def test_no_user_text_is_empty(self):
        self.assertEqual(media.prompt_from_input(
            [{'role': 'assistant', 'content': 'hi'}]), '')
        self.assertEqual(media.prompt_from_input([]), '')

    def test_textless_latest_user_message_does_not_reuse_an_old_prompt(self):
        self.assertEqual(media.prompt_from_input([
            {'role': 'user', 'content': 'old prompt'},
            {'role': 'user', 'content': [{'type': 'input_image'}]}]), '')


class ToolTests(unittest.TestCase):
    def test_finds_each_media_tool(self):
        kind, tool = media.media_tool({'tools': [{'type': 'image_generation'}]})
        self.assertEqual((kind, tool), ('image', {'type': 'image_generation'}))
        kind, _ = media.media_tool({'tools': [{'type': 'video_generation'}]})
        self.assertEqual(kind, 'video')

    def test_no_media_tool_is_none(self):
        self.assertEqual(media.media_tool({'tools': []}), (None, None))
        self.assertEqual(media.media_tool({}), (None, None))


class BodyTests(unittest.TestCase):
    def test_image_body_carries_model_and_prompt(self):
        body = media.image_body('openai/gpt-image-2',
                                {'input': [{'role': 'user', 'content': 'a cat'}]},
                                {'type': 'image_generation'})
        self.assertEqual(body, {'model': 'openai/gpt-image-2', 'prompt': 'a cat'})

    def test_video_body_carries_model_and_prompt(self):
        body = media.video_body('google/veo-3.1-fast',
                                {'input': [{'role': 'user', 'content': 'push-in'}]},
                                {'type': 'video_generation'})
        self.assertEqual(body, {'model': 'google/veo-3.1-fast', 'prompt': 'push-in'})

    def test_missing_prompt_is_refused(self):
        with self.assertRaises(PreparationError):
            media.image_body('m', {'input': []}, {'type': 'image_generation'})
        with self.assertRaises(PreparationError):
            media.video_body('m', {'input': []}, {'type': 'video_generation'})


class AnswerTests(unittest.TestCase):
    def test_image_bytes_become_a_model_message(self):
        raw = json.dumps({'model': 'openai/gpt-image-2', 'created': 1,
                          'data': [{'b64_json': 'QUJD',
                                    'media_type': 'image/png'}]}).encode()
        answer = media.image_answer('openai/gpt-image-2', raw)
        self.assertEqual(answer['status'], 'completed')
        call, = answer['output']
        self.assertEqual(call['type'], 'image_generation_call')
        self.assertEqual(call['status'], 'completed')
        self.assertEqual(call['result'], 'QUJD')
        self.assertIsInstance(call['id'], str)

    def test_empty_image_data_is_refused(self):
        with self.assertRaises(PreparationError):
            media.image_answer('m', b'{"data": []}')

    def test_multiple_generated_images_are_retained_with_distinct_ids(self):
        raw = json.dumps({'data': [{'b64_json': 'QQ=='}, {'b64_json': 'Qg=='}]}).encode()
        output = media.image_answer('m', raw)['output']
        self.assertEqual([item['result'] for item in output], ['QQ==', 'Qg=='])
        self.assertEqual(len({item['id'] for item in output}), 2)

    def test_video_job_names_id_and_poll_url(self):
        raw = json.dumps({'id': 'abc123', 'model': 'google/veo-3.1-fast',
                          'status': 'pending',
                          'polling_url': 'https://openrouter.ai/api/v1/videos/abc123'}).encode()
        answer = media.video_answer('google/veo-3.1-fast', raw)
        text = answer['output'][0]['content'][0]['text']
        self.assertIn('abc123', text)
        self.assertIn('https://openrouter.ai/api/v1/videos/abc123', text)

    def test_job_without_id_is_refused(self):
        with self.assertRaises(PreparationError):
            media.video_answer('m', b'{"status": "pending"}')

    def test_relative_video_polling_url_names_the_provider(self):
        reply = media.Response(json.dumps({'id': 'job',
            'polling_url': '/api/v1/videos/job'}).encode(), 'application/json')
        reply.status = 202
        answer = media.normalize('video', 'm', provider_defs.OPENROUTER.host,
                                 reply, False, {})
        text = json.loads(answer.read())['output'][0]['content'][0]['text']
        self.assertIn('https://openrouter.ai/api/v1/videos/job', text)


class EvidenceTests(unittest.TestCase):
    def test_video_identity_reports_come_only_from_the_original_provider_reply(self):
        harness = RouteHarness(self)
        requested = 'google/veo-3.1-fast'
        for streaming in (False, True):
            for reported in (None, requested, 'google/different-video-model'):
                with self.subTest(streaming=streaming, reported=reported):
                    job = {'id': 'job_fixture', 'status': 'pending',
                           'polling_url': '/api/v1/videos/job_fixture'}
                    if reported is not None:
                        job['model'] = reported
                    reply = FakeUpstream(202, json.dumps(job).encode(),
                                         [('Content-Type', 'application/json')])
                    status, _, sends, facts = harness.turn(
                        media_payload(requested, 'video', streaming),
                        provider_defs.RESPONSES, [reply], projected=False)
                    self.assertEqual((status, len(sends)), (200, 1))
                    evidence, = facts['attempt_evidence']
                    expected = ('unverified' if reported is None else
                                'provider_reported_match' if reported == requested else 'mismatch')
                    self.assertEqual(evidence['model_status'], expected)
                    self.assertEqual(evidence['model_reports'], [] if reported is None else
                                     [{'value': reported, 'source': 'response.media.model'}])
                    self.assertEqual(evidence['effort_status'], 'unverified')
                    self.assertEqual(evidence['effort_reports'], [])


class AvailabilityTests(unittest.TestCase):
    def test_media_catalogue_does_not_trigger_compaction_with_a_zero_chat_budget(self):
        row = catalogue.external_entry(registry.by_slug('google/veo-3.1-fast'))
        self.assertIsNone(row['context_window'])
        self.assertIsNone(row['max_context_window'])

    def test_key_filtered_fetch_includes_media_output_modalities(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"data": []}'
        fetch = mock.Mock(return_value=response)
        availability.fetch(provider_defs.OPENROUTER.host, 'synthetic-key', fetch)
        query = parse_qs(urlsplit(fetch.call_args.args[0].full_url).query)
        self.assertEqual(query['output_modalities'], ['text,image,video'])


if __name__ == '__main__':
    unittest.main()
