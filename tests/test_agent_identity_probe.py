"""The paid-free mapping gate cannot accept V2 or a guessed child mapping."""
import unittest

from tools.probe_agent_identity import CALLS, IdentityProbe
from tests.test_agent_identity import CHILD, OTHER


class IdentityProbeTests(unittest.TestCase):
    def test_two_exact_ids_and_overlap_are_both_required(self):
        probe = IdentityProbe(False, 0)
        probe.returned_ids = dict(zip(CALLS, (CHILD, OTHER)))
        probe.child_threads = {CHILD, OTHER}
        self.assertFalse(probe.verify())
        probe.children_ready.set()
        self.assertTrue(probe.verify())
        probe.returned_ids[CALLS[1]] = CHILD
        self.assertFalse(probe.verify())

    def test_v2_declaration_cannot_satisfy_v1_proof(self):
        probe = IdentityProbe(False, 0)
        with self.assertRaises(ValueError):
            probe.tool({'tools': [{'type': 'namespace', 'name': 'collaboration',
                       'tools': [{'name': 'spawn_agent'}]}]}, 'spawn_agent')

    def test_recorded_tool_failure_invalidates_exact_mapping(self):
        probe = IdentityProbe(False, 0)
        probe.returned_ids = dict(zip(CALLS, (CHILD, OTHER)))
        probe.child_threads = {CHILD, OTHER}
        probe.children_ready.set()
        probe.facts['tool_failures'].append('synthetic_failure')
        self.assertFalse(probe.verify())
