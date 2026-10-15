"""One submission must produce bytes, not merely a video job reference."""
import io
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_router import availability, media_cli
from ai_router.errors import PreparationError
from tests.fakes import FakeUpstream, install_fake
from tests.harness import StubCredentials
from tools.probe_media import red_png

CLIP = b'\x00\x00\x00\x18ftypmp42' + b'fixture-video'


class MediaCommandTests(unittest.TestCase):
    def generate(self, output, job_id=None):
        return media_cli.generate('video', 'z-ai/glm-5.3', 'google/veo-3.1-fast',
                                  'synthetic video', output, {}, StubCredentials(), job_id=job_id)

    def test_video_downloads_completed_clip_without_following_returned_urls(self):
        replies = iter((FakeUpstream(202, b'{"id":"job-fixture","status":"pending","polling_url":"https://evil.invalid"}'),
                        FakeUpstream(200, b'{"id":"job-fixture","status":"completed"}'),
                        FakeUpstream(200, CLIP)))
        sends = install_fake(self, lambda: next(replies))
        with tempfile.TemporaryDirectory() as home, mock.patch.object(media_cli.time, 'sleep'):
            path = self.generate(Path(home, 'clip.mp4'))
            self.assertEqual(path.read_bytes(), CLIP)
        self.assertEqual([(s[0], s[1], s[2]) for s in sends], [
            ('openrouter.ai', 'POST', '/api/v1/videos'),
            ('openrouter.ai', 'GET', '/api/v1/videos/job-fixture'),
            ('openrouter.ai', 'GET', '/api/v1/videos/job-fixture/content?index=0')])
        self.assertEqual(json.loads(sends[0][3])['duration'], 4)

    def test_timeout_keeps_job_id_and_resume_does_not_submit_again(self):
        sends = install_fake(self, lambda: FakeUpstream(200, b'{"id":"job-fixture","status":"pending"}'))
        with tempfile.TemporaryDirectory() as home, mock.patch.object(media_cli.time, 'sleep'), \
                mock.patch.object(media_cli, 'MAX_POLLS', 2):
            output = Path(home, 'clip.mp4')
            with self.assertRaisesRegex(PreparationError, 'retain job job-fixture'):
                self.generate(output, job_id='job-fixture')
            self.assertEqual(output.read_bytes(), b'')
        self.assertEqual([s[1] for s in sends], ['GET', 'GET'])

    def test_existing_destination_is_refused_before_a_paid_call(self):
        sends = install_fake(self, lambda: self.fail('must not send'))
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, 'clip.mp4')
            path.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                self.generate(path)
            self.assertEqual(path.read_bytes(), b'keep')
        self.assertEqual(sends, [])

    def test_provider_failure_does_not_retry_submission(self):
        sends = install_fake(self, lambda: FakeUpstream(503, b'failure'))
        with tempfile.TemporaryDirectory() as home:
            with self.assertRaises(PreparationError):
                self.generate(Path(home, 'clip.mp4'))
        self.assertEqual(len(sends), 1)

    def test_poll_failure_or_completion_preserves_another_writers_replacement_file(self):
        for completed in (False, True):
            with self.subTest(completed=completed), tempfile.TemporaryDirectory() as home:
                output = Path(home, 'clip.mp4')
                reserved = Path(home, 'reserved.mp4')
                original_open = Path.open

                def open_destination(path, mode='r', *args, **kwargs):
                    # Model an already-replaced open handle on all platforms.
                    return original_open(reserved if mode == 'xb' else path, mode, *args, **kwargs)

                def respond():
                    if len(sends) == 3:
                        return FakeUpstream(200, CLIP)
                    if output.exists():
                        self.fail('only one poll should run')
                    if len(sends) == 1:
                        return FakeUpstream(202, b'{"id":"job-fixture","status":"pending"}')
                    output.write_bytes(b'another writers completed clip')
                    if completed:
                        return FakeUpstream(200, b'{"id":"job-fixture","status":"completed"}')
                    raise TimeoutError('synthetic polling failure')

                sends = install_fake(self, respond)
                with mock.patch.object(Path, 'open', open_destination), \
                        mock.patch.object(media_cli.time, 'sleep'), mock.patch('sys.stderr', new_callable=io.StringIO):
                    with self.assertRaisesRegex(PreparationError, 'retain job job-fixture'):
                        self.generate(output)
                self.assertEqual(output.read_bytes(), b'another writers completed clip')

    def test_policy_denials_and_native_chat_send_nothing(self):
        sends = install_fake(self, lambda: self.fail('must not send'))
        with tempfile.TemporaryDirectory() as home:
            output = Path(home, 'clip.mp4')
            for chat, config, permitted in (('gpt-6-astra', {}, True),
                    ('z-ai/glm-5.3', {'allowed_models': ['z-ai/glm-5.3']}, True),
                    ('z-ai/glm-5.3', {}, False)):
                with self.subTest(chat=chat, config=config), \
                        mock.patch.object(availability, 'permitted', return_value=permitted):
                    with self.assertRaises((PreparationError, ValueError)):
                        media_cli.generate('video', chat, 'google/veo-3.1-fast',
                            'synthetic video', output, config, StubCredentials())
                    self.assertFalse(output.exists())
        self.assertEqual(sends, [])

    def test_image_command_saves_verified_png_on_the_chat_provider(self):
        sends = install_fake(self, lambda: FakeUpstream(200, json.dumps({
            'created': 1, 'data': [{'b64_json': base64.b64encode(red_png()).decode()}]}).encode()))
        with tempfile.TemporaryDirectory() as home:
            result = media_cli.generate('image', 'openai/gpt-6-luna', 'openai/gpt-image-2',
                'a red square', Path(home, 'new.png'), {}, StubCredentials())
            self.assertEqual(result.read_bytes(), red_png())
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][:3], ('openrouter.ai', 'POST', '/api/v1/images'))

    def test_command_restores_key_scoped_availability_before_sending(self):
        sends = install_fake(self, lambda: self.fail('must not send'))
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(availability, '_SNAPSHOTS', {}), \
                mock.patch.object(availability, '_HAD_SNAPSHOT', set()), \
                mock.patch.object(media_cli.state, 'default_home', return_value=Path(home)), \
                mock.patch.object(media_cli.state, 'read_strict', return_value={}), \
                mock.patch.object(media_cli.credentials, 'Credentials', return_value=StubCredentials()), \
                mock.patch('sys.argv', ['media_cli', 'video', '--chat-model', 'openai/gpt-6-luna',
                                       '--output', str(Path(home, 'new.mp4'))]), \
                mock.patch('sys.stderr', new_callable=io.StringIO):
            availability.snapshot_store.write(
                home, 'openrouter', availability.key_fingerprint('router-secret'),
                'global', ['openai/gpt-6-luna'])
            with self.assertRaises(SystemExit) as stopped:
                media_cli.main()
            self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(sends, [])

    def test_accepted_job_remains_recoverable_after_poll_or_download_failure(self):
        completed = FakeUpstream(200, b'{"id":"job-fixture","status":"completed"}')
        cases = ((FakeUpstream(503, b'failure'),), (TimeoutError('synthetic timeout'),),
                 (completed, FakeUpstream(503, b'failure')))
        for failures in cases:
            with self.subTest(failures=len(failures)):
                pending = FakeUpstream(202, b'{"id":"job-fixture","status":"pending"}')
                replies = iter((pending, *failures))

                def respond():
                    reply = next(replies)
                    if isinstance(reply, Exception):
                        raise reply
                    return reply

                sends = install_fake(self, respond)
                with tempfile.TemporaryDirectory() as home, mock.patch.object(media_cli.time, 'sleep'), \
                        mock.patch('sys.stderr', new_callable=io.StringIO) as receipt:
                    output = Path(home, 'clip.mp4')
                    with self.assertRaisesRegex(PreparationError, 'retain job job-fixture'):
                        self.generate(output)
                    self.assertEqual(output.read_bytes(), b'')
                    self.assertEqual(json.loads(receipt.getvalue()),
                                     {'status': 'accepted', 'job_id': 'job-fixture'})
                self.assertEqual([send[1] for send in sends], ['POST'] + ['GET'] * len(failures))
