"""Offline status pages retain evidence boundaries and work as one portable file."""
from html.parser import HTMLParser
import base64
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_agent_skills import release, skills


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT.parent / 'plugins/agents/scg-agent-factory/skills/ai-agent-factory-method'
ASSETS = SKILL / 'assets/status'
spec = importlib.util.spec_from_file_location('factory_status_builder', SKILL / 'scripts/build_status.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.starts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.starts.append((tag, dict(attrs)))


class FactoryStatusBuilderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / 'records.json'
        self.output = self.root / 'status.html'
        self.data = json.loads((ASSETS / 'example.json').read_text(encoding='utf-8'))

    def build(self):
        self.source.write_text(json.dumps(self.data), encoding='utf-8')
        return builder.build(self.source, self.output).read_text(encoding='utf-8')

    def test_inline_page_preserves_text_without_turning_it_into_markup(self):
        self.data['features'][0]['outcome'] = '</script><script src="https://example.com/run.js"></script>'
        html = self.build()
        elements = Elements(html).starts
        scripts = [attrs for tag, attrs in elements if tag == 'script']
        self.assertEqual(scripts, [{'id': 'status-data', 'type': 'application/json'}, {'type': 'module'}])
        self.assertFalse(any(tag in {'link', 'iframe', 'form'} for tag, _ in elements))
        raw = html.split('<script id="status-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        payload = json.loads(raw)
        self.assertEqual(payload['records'], self.data)
        self.assertEqual(payload['records']['project']['checked'], '')
        self.assertIn('generatedAt', payload)
        self.assertNotIn('fetch(', html)

    def test_example_cannot_become_real_reporting_by_toggling_one_flag(self):
        self.output.write_text('previous verified page', encoding='utf-8')
        self.data['project']['template'] = False
        with self.assertRaisesRegex(ValueError, 'Replace example'):
            self.build()
        self.assertEqual(self.output.read_text(), 'previous verified page')

    def test_template_flag_must_be_boolean(self):
        self.data['project']['template'] = 'false'
        with self.assertRaisesRegex(ValueError, 'true or false'):
            self.build()

    def test_screenshot_is_embedded_and_missing_input_preserves_previous_page(self):
        (self.root / 'screenshots').mkdir()
        image = self.root / 'screenshots/view.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.data['features'][0]['screenshots'] = [{'src': 'screenshots/view.png'}]
        html = self.build()
        raw = html.split('<script id="status-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        image_uri = json.loads(raw)['images']['screenshots/view.png']
        self.assertTrue(image_uri.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(image_uri.split(',', 1)[1]), image.read_bytes())
        image.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertEqual(self.output.read_text(encoding='utf-8'), html)

    def test_screenshot_cannot_select_an_arbitrary_file(self):
        self.data['features'][0]['screenshots'] = [{'src': '../private.png'}]
        with self.assertRaisesRegex(ValueError, 'local PNG'):
            self.build()

    def test_output_cannot_replace_source_records(self):
        self.source.write_text(json.dumps(self.data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'must not replace'):
            builder.build(self.source, self.source)
        self.assertEqual(json.loads(self.source.read_text()), self.data)

    def test_bundle_and_both_marketplace_views_include_the_actual_builder_and_assets(self):
        target = self.root / 'marketplace'
        skills.write_marketplace(target, ROOT.parent / 'plugins')
        packaged = set(release.plugin_files(ROOT))
        for source in [SKILL / 'scripts/build_status.py', *ASSETS.iterdir()]:
            relative = source.relative_to(SKILL)
            self.assertIn(source.relative_to(ROOT.parent).as_posix(), packaged)
            delivered = target / 'plugins/scg-agent-factory/skills/ai-agent-factory-method' / relative
            self.assertEqual(delivered.read_bytes(), source.read_bytes())
        delivered_builder = target / 'plugins/scg-agent-factory/skills/ai-agent-factory-method/scripts/build_status.py'
        self.source.write_text(json.dumps(self.data), encoding='utf-8')
        result = subprocess.run([sys.executable, str(delivered_builder),
                                 '--data', str(self.source), '--output', str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.output.is_file())


@unittest.skipUnless(shutil.which('node'), 'Node is needed only for JavaScript model development tests')
class FactoryStatusModelTests(unittest.TestCase):
    def test_completion_human_input_and_unknown_states(self):
        script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const m = await import(process.argv[1]);
const example = JSON.parse(readFileSync(process.argv[2], 'utf8'));
example.project.template = false;
assert.throws(() => m.validate(example), /Replace example/);
const evidence = [{label: 'Verified source record', url: 'https://github.com/example/project/commit/abc123'}];
const f = {id: 'one', title: 'Search customers', scope: 'active', kind: 'implementation', build: 'Merged',
  releases: [{state: 'Released', environment: 'Production', audience: 'All intended users', revision: 'abc123', evidence}],
  acceptance: {state: 'Accepted', owner: 'Sample checker', acceptedAt: '2026-10-31T10:00:00+11:00', environment: 'Production', revision: 'abc123', evidence},
  criteria: [{id: 'find-1', text: 'Returns the matching customer', state: 'Passed', evidence}]};
assert.equal(m.delivery(f).group, 'done');
assert.equal(m.delivery({...f, target: '2026-01-01'}, {}, Date.parse('2026-11-01T00:00:00Z')).group, 'done');
const local = structuredClone(f);
for (const holder of [local.releases[0], local.acceptance, local.criteria[0]]) holder.evidence = [{label: 'Local source record', reference: 'checks/search-abc123.txt'}];
assert.equal(m.delivery(local).group, 'done');
local.acceptance.evidence[0].reference = '[acceptance record]';
assert.notEqual(m.delivery(local).group, 'done');
for (const [field, value] of [['owner',''], ['owner','[Checker]'], ['acceptedAt',''], ['revision','different']]) {
  const changed = structuredClone(f); changed.acceptance[field] = value;
  assert.notEqual(m.delivery(changed).group, 'done', field);
}
const placeholder = structuredClone(f); placeholder.acceptance.evidence[0].url = 'https://example.com/acceptance';
assert.notEqual(m.delivery(placeholder).group, 'done');
const blocked = {...f, blocker: 'Search returns the wrong customer'};
assert.notEqual(m.delivery(blocked).group, 'done');
const dependency = {...f, dependencies: [{id: 'input', state: 'Open'}]};
assert.notEqual(m.delivery(dependency).group, 'done');
const testOnly = structuredClone(f); testOnly.releases[0].environment = testOnly.acceptance.environment = 'Staging';
assert.notEqual(m.delivery(testOnly).group, 'done');
const missingProof = structuredClone(f); missingProof.acceptance.state = 'Pending'; missingProof.releases[0].evidence = [];
assert.equal(m.delivery(missingProof).tag, 'Availability unconfirmed');
const merged = {...f, releases: [], acceptance: {state: 'Pending'}};
assert.equal(m.delivery(merged).tag, 'Ready to publish');
assert.equal(m.delivery({...merged, build: 'Not recorded'}).group, 'unknown');
assert.equal(m.delivery({...merged, build: 'Planned'}).group, 'todo');
const questions = {...merged, decisions: [
  {text: 'Record the release proof', owner: 'Engineering', audience: 'team'},
  {text: 'Choose the first audience', owner: 'Project owner', audience: 'human'},
  {text: 'Choose the colour', owner: 'Project owner', audience: 'human', result: 'Pink'},
  {text: 'Unassigned question', owner: '', audience: 'human'}]};
assert.equal(m.humanRequests(questions).length, 1);
assert.equal(m.humanRequests({...questions, scope: 'deferred'}).length, 0);
const waiting = {...merged, decisions: [{text: 'Choose the first audience', owner: 'Project owner', audience: 'human', result: 'Not recorded', due: '2026-10-30'}]};
const decisionNow = Date.parse('2026-11-01T00:00:00Z');
assert.equal(m.humanRequests(waiting).length, 1, 'An unknown result is still an open question');
assert(m.flags(waiting, {}, decisionNow).includes('Decision date passed'));
assert.equal(m.delivery(waiting, {}, decisionNow).warning, 'Overdue');
waiting.decisions[0].result = 'Only the project team';
assert.equal(m.humanRequests(waiting).length, 0);
assert(!m.flags(waiting, {}, decisionNow).includes('Decision date passed'));
assert.equal(m.delivery(waiting, {}, decisionNow).warning, '');
const data = {schemaVersion: 1, project: {title: 'Sample'}, features: [f, testOnly, {...merged, scope: 'deferred'}], tasks: []};
assert.equal(m.counts(data).total, 2);
assert.equal(m.counts(data).accepted, 1);
console.log('evidence and reader-state cases passed');
'''
        result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script,
                                 (ASSETS / 'delivery-model.mjs').as_uri(), str(ASSETS / 'example.json')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('cases passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
