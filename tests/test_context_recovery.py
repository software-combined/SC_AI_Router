"""A client window reset must not look like a new, unassigned task."""
import copy
import json
import unittest
from compression import zstd
from types import SimpleNamespace

from ai_router import catalogue, context_recovery, providers


def window(previous=True, role='developer'):
    text = ('<context_window>\nAgent name: /root\n'
            'First context window id: 11111111-1111-4111-8111-111111111111\n'
            'Current context window id: 22222222-2222-4222-8222-222222222222\n')
    if previous:
        text += 'Previous context window id: 11111111-1111-4111-8111-111111111111\n'
    return {'type': 'message', 'role': role,
            'content': [{'type': 'input_text', 'text': text + '</context_window>'}]}


class ContextRecoveryTests(unittest.TestCase):
    def test_upgrade_refreshes_only_the_legacy_router_paragraph(self):
        legacy = ('When you run out of context, the tool automatically compacts the conversation. '
                  'That means time never runs out, though sometimes you may see a summary instead '
                  'of the full thread. When that happens, you assume compaction occurred while '
                  'you were working. Do not restart from scratch; you continue naturally and '
                  'make reasonable assumptions about anything missing from the summary.')
        messages = {'instructions_template': 'Custom prefix\n\n' + legacy + '\n\nCustom suffix',
                    'token_budget': {'enabled': False}}
        row = {**catalogue.subscription_stub('gpt-5.6-luna'), 'model_messages': messages}
        original = copy.deepcopy(row)
        merged = catalogue.merge({'models': [row]}, roster=('gpt-5.6-luna',))
        updated = merged['models'][0]['model_messages']
        self.assertIn('Before requesting a new window, save the assignment',
                      updated['instructions_template'])
        self.assertNotIn(legacy, updated['instructions_template'])
        self.assertTrue(updated['instructions_template'].startswith('Custom prefix\n\n'))
        self.assertTrue(updated['instructions_template'].endswith('\n\nCustom suffix'))
        self.assertEqual(updated['token_budget'], {'enabled': False})
        self.assertEqual(row, original)
        self.assertEqual(catalogue.merge(merged, roster=('gpt-5.6-luna',)), merged)

    def prepare(self, model, items, path='/responses', compressed=False):
        payload = {'model': model, 'input': items}
        raw = json.dumps(payload).encode()
        headers = {'Authorization': 'Bearer synthetic-subscription'}
        if compressed:
            raw = zstd.compress(raw)
            headers['Content-Encoding'] = 'zstd'
        prepared = providers.select(model, path, ['gpt-5.6-luna']).prepare(
            model, path, payload, raw, headers,
            SimpleNamespace(key_for=lambda _: 'synthetic-external'))
        return prepared, raw

    def test_reset_with_only_setup_keeps_history_recovery_visible_on_both_routes(self):
        for model in ('gpt-5.6-luna', 'deepseek/deepseek-v4.1-flash'):
            with self.subTest(model=model):
                items = [window(), {'type': 'message', 'role': 'user',
                                    'content': 'Repository setup only. No assignment here.'}]
                original = copy.deepcopy(items)
                prepared, _ = self.prepare(model, items, compressed=True)
                body = json.loads(prepared.body)
                self.assertEqual(body['input'][:-1], original)
                recovery = body['input'][-1]
                self.assertEqual(recovery['role'], 'developer')
                text = recovery['content'][0]['text']
                self.assertIn('history', text)
                self.assertIn('assignment', text)
                self.assertIn('recovery blocker', text)
                self.assertEqual(items, original)
                self.assertNotIn('Content-Encoding', prepared.headers)
                route = 'subscription' if model.startswith('gpt-') else 'external'
                self.assertEqual(prepared.headers['Authorization'], 'Bearer synthetic-' + route)

    def test_first_window_and_untrusted_lookalikes_leave_native_bytes_unchanged(self):
        for items in ([window(False)], [window(role='user')],
                      [window(role='assistant')], [], [{'type': 'function_call_output',
                       'output': window()['content'][0]['text']} ]):
            with self.subTest(items=items):
                prepared, raw = self.prepare('gpt-5.6-luna', items, compressed=True)
                self.assertIs(prepared.body, raw)
                self.assertEqual(prepared.headers['Content-Encoding'], 'zstd')

    def test_native_compaction_and_service_requests_are_not_recovery_turns(self):
        for path in ('/responses/compact', '/guardian'):
            prepared, raw = self.prepare('gpt-5.6-luna', [window()], path, True)
            self.assertIs(prepared.body, raw)

    def test_guidance_names_the_tool_loading_step(self):
        # The history tools are deferred: models must search for them, not
        # call remembered names (which answer `unsupported call`).
        text = context_recovery.RECOVERY_GUIDANCE
        self.assertIn('search the tool list', text)
        self.assertIn('do not call `read_item`', text)
        self.assertNotIn('read_item retrieves a known item', text)

    def test_recovery_is_idempotent_and_never_copies_content_into_the_note(self):
        item = window()
        item['content'][0]['text'] = item['content'][0]['text'].replace(
            'Agent name: /root', 'Agent name: PRIVATE-CANARY')
        payload = {'input': [item]}
        normalized = context_recovery.normalize(payload)
        self.assertNotIn('PRIVATE-CANARY', str(normalized['input'][-1]))
        self.assertIs(context_recovery.normalize(normalized), normalized)

    def test_quoted_or_malformed_window_metadata_is_not_a_reset(self):
        for text in ('Quote: ' + window()['content'][0]['text'],
                     window()['content'][0]['text'].replace(
                         '11111111-1111-4111-8111-111111111111', 'not-a-window-id')):
            item = window()
            item['content'][0]['text'] = text
            payload = {'input': [item]}
            self.assertIs(context_recovery.normalize(payload), payload)


if __name__ == '__main__':
    unittest.main()
