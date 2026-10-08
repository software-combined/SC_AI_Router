"""Media translation: prompt extraction, bodies and answer shapes."""
import json
import unittest

from ai_router import media
from ai_router.errors import PreparationError


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


if __name__ == '__main__':
    unittest.main()
