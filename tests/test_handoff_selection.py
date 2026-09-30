"""The parent selects a child and a provider-compatible, readable handoff."""
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from ai_router import agent_handoffs
from tests.test_agent_handoffs import native_tools
from tests.test_codex_preferences import codex_config
from tests.test_lite_handoffs import lite

ROOT = Path(__file__).resolve().parents[1]


class SelectionGuidanceTests(unittest.TestCase):
    def test_both_wire_shapes_explain_selection_and_recipient_route(self):
        for payload in ({'tools': native_tools('spawn_agent', 'send_message', 'followup_task')}, lite()):
            original = deepcopy(payload)
            prepared, _ = agent_handoffs.add_plaintext_tools(payload)
            tools = prepared.get('tools', prepared.get('input', [{}])[0].get('tools'))
            native, aliases = tools
            for namespace in (native, aliases):
                for tool in namespace['tools']:
                    description = tool['description']
                    self.assertIn('recipient', description)
                    self.assertIn('GPT through OpenRouter', description)
                    self.assertIn('collaboration_plaintext.' + tool['name'], description)
                    if tool['name'] == 'spawn_agent':
                        self.assertIn('model and reasoning_effort explicitly', description)
                        self.assertIn('fork_turns="none"', description)
            self.assertEqual(payload, original)
            for old, new in zip(original.get('tools', original.get('input', [{}])[0].get('tools'))[0]['tools'], native['tools']):
                self.assertEqual({k: v for k, v in old.items() if k != 'description'},
                                 {k: v for k, v in new.items() if k != 'description'})

    def test_review_example_selects_exact_policy_route_and_fresh_context(self):
        path = ROOT / 'plugins/scg-review/skills/pre-commit-review/SKILL.md'
        text = path.read_text()
        dispatch = json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))
        self.assertEqual(dispatch['model'], 'openai/gpt-6.1-sol')
        self.assertEqual(dispatch['reasoning_effort'], 'high')
        self.assertEqual(dispatch['fork_turns'], 'none')
        self.assertIn('collaboration_plaintext.spawn_agent', text)
        self.assertIn('collaboration_plaintext.followup_task', text)
        self.assertIn('encrypted message containing a file path', text)


class InstallerSelectionTests(unittest.TestCase):
    def test_install_and_update_leave_subagent_defaults_to_the_owner(self):
        initial = ('', '[agents]\ndefault_subagent_reasoning_effort = "max"\n',
                   '[agents]\ndefault_subagent_model = "z-ai/glm-5.3-flash"\n'
                   'default_subagent_reasoning_effort = "max"\n')
        for mode in ('subscription', 'none'):
            for text in initial:
                with self.subTest(mode=mode, initial=text), tempfile.TemporaryDirectory() as tmp:
                    config = Path(tmp) / 'config.toml'
                    config.write_text(text)
                    expected = tomllib.loads(text).get('agents', {})
                    previous = None
                    writer = type('Writer', (), {'replace_text': staticmethod(lambda p, t: Path(p).write_text(t))})
                    with patch.object(codex_config, '_atomic_write', writer):
                        for version in ('1.0.0', '1.0.1'):
                            block = codex_config.build_block(Path(tmp) / version,
                                {'port': 1234, 'token': 'synthetic'}, mode, static_catalogue=True)
                            block, _, desktop, reviewer = codex_config.attach_config(config, block, previous)
                            previous = {'inserted_block': block, 'desktop': desktop, 'reviewer': reviewer}
                            self.assertEqual(tomllib.loads(config.read_text()).get('agents', {}), expected)


if __name__ == '__main__':
    unittest.main()
