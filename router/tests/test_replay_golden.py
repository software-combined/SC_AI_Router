"""Replay goldens: each synthetic history's exact wire body per route (Plan 182).

Every fixture under `tests/fixtures/replay/` is one synthetic Codex history
plus the rows it matters to. Each fixture-target pair runs through the
provider's `prepare` with the row's slug as the client's `model`, as the
router passes it, and the wire body plus `wire_shape.violations` must match
the committed golden in `expected/`. Any projection change is therefore a
reviewable diff, and Plan 183's refactor must leave every golden
byte-identical.

`REPLAY_GOLDEN_UPDATE=1 python3.14 -m unittest tests.test_replay_golden`
rewrites the goldens instead of comparing. That is a behaviour change: the PR
explains the golden diff, and `CHANGELOG.md` does too when users see it.
A golden's name replaces the target's `:` and `/` with `_`, because a colon
is not a legal file name on the Windows CI runners that check out the tree.
"""
import copy
import json
import os
import unittest
from pathlib import Path

from ai_router import provider_defs, request_context, wire_shape
from ai_router.providers import ExternalResponsesProvider, SubscriptionProvider
from tests.harness import StubCredentials, isolated_home, stub_credentials

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'replay'
EXPECTED = FIXTURES / 'expected'


def golden_name(fixture, target):
    return f'{fixture}__{target.replace(":", "_").replace("/", "_")}.json'


def golden(target, payload):
    """{'wire', 'contract'} for one `<route>:<slug>` target, or {'error'}."""
    route, slug = target.split(':', 1)
    payload = dict(copy.deepcopy(payload), model=slug)
    context = request_context.resolve(slug, request_context.capture())
    try:
        if route == 'subscription':
            provider = SubscriptionProvider()
            # A resolving external key: the install shape that ships readable briefs.
            prepared = provider.prepare(slug, '/responses', payload, json.dumps(payload).encode(),
                                        {}, StubCredentials(), context=context)
        else:
            provider = ExternalResponsesProvider(provider_defs.OPENROUTER)
            prepared = provider.prepare(slug, '/responses', payload, b'', {},
                                        stub_credentials(), context=context)
    except Exception as exc:  # noqa: BLE001 - any refusal is pinned behaviour
        return {'error': f'{type(exc).__name__}: {exc}'}
    wire = json.loads(prepared.body)
    observed = getattr(context.row, 'observed_item_types', ())
    return {'wire': wire, 'contract': wire_shape.violations(provider.defn.dialect, wire, observed)}


class ReplayGoldenTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        isolated_home(self)

    def test_every_fixture_target_pair_matches_its_golden(self):
        update = os.environ.get('REPLAY_GOLDEN_UPDATE') == '1'
        names = []
        for path in sorted(FIXTURES.glob('*.json')):
            fixture = json.loads(path.read_text(encoding='utf-8'))
            for target in fixture['targets']:
                name = golden_name(path.stem, target)
                names.append(name)
                text = json.dumps(golden(target, fixture['payload']),
                                  sort_keys=True, indent=1) + '\n'
                with self.subTest(golden=name):
                    if update:
                        EXPECTED.mkdir(exist_ok=True)
                        (EXPECTED / name).write_text(text, encoding='utf-8')
                    else:
                        self.assertEqual((EXPECTED / name).read_text(encoding='utf-8'), text)
        # A golden whose fixture or target is gone would pass silently forever.
        self.assertEqual(sorted(path.name for path in EXPECTED.glob('*.json')), sorted(names))


if __name__ == '__main__':
    unittest.main()
