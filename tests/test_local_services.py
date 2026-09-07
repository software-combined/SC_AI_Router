import json
import unittest
from codex_router import local_services


class LocalServicesTests(unittest.TestCase):
    def test_thread_hint_and_search_raise_404_without_recorded_shape(self):
        for path in ('/alpha/notes/v2/thread_hint', '/alpha/search'):
            with self.subTest(path=path):
                with self.assertRaises(local_services.LocalAnswer) as ctx:
                    local_services.answer(path)
                self.assertEqual(ctx.exception.status, 404)

    def test_guardian_names_approvals_reviewer_setting(self):
        for path in ('/guardian', '/guardian-classifier'):
            with self.subTest(path=path):
                with self.assertRaises(local_services.LocalAnswer) as ctx:
                    local_services.answer(path)
                self.assertEqual(ctx.exception.status, 404)
                self.assertIn('approvals_reviewer', ctx.exception.message)

    def test_answers_are_logged(self):
        with self.assertLogs('codex_router', level='INFO') as logs:
            with self.assertRaises(local_services.LocalAnswer):
                local_services.answer('/alpha/search')
        events = [json.loads(record.getMessage()) for record in logs.records]
        service = [e for e in events if e.get('event') == 'local_service']
        self.assertEqual(len(service), 1)
        self.assertEqual(service[0]['path'], '/alpha/search')
