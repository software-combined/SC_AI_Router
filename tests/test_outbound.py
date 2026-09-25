"""Plan 183: each Responses route runs one named stage list, in this order.

A reorder, an added stage or a dropped one is a visible edit here, reviewed
against the goldens. Stage modules never resolve a row themselves: the
adapter passes the request's captured row in.
"""
import unittest

from ai_router import outbound, tool_adapter, tool_history


def _names(stages):
    return [stage.__name__ for stage in stages]


class StageOrderTests(unittest.TestCase):
    def test_external_stage_order(self):
        self.assertEqual(_names(outbound.EXTERNAL_STAGES), [
            'refuse_opaque_briefs', 'recover_context', 'materialize_standalone',
            'scrub_fragments', 'add_handoff_tools', 'hint_lanes', 'declare_tools',
            'rewrite_history', 'compaction_text', 'strip_reasoning', 'note_media',
            'check_effort', 'drop_native_fields', 'upstream_model', 'output_cap'])

    def test_subscription_stage_order(self):
        self.assertEqual(_names(outbound.SUBSCRIPTION_STAGES), [
            'replay_boundary', 'replay_reasoning', 'recover_context',
            'add_handoff_tools', 'hint_lanes'])
        self.assertEqual(outbound.SUBSCRIPTION_STAGES[:2], outbound.SUBSCRIPTION_REPLAY)

    def test_stage_modules_hold_no_registry_lookup(self):
        for module in (outbound, tool_adapter, tool_history):
            with self.subTest(module=module.__name__):
                self.assertFalse(hasattr(module, 'by_slug'))


if __name__ == '__main__':
    unittest.main()
