"""Offline checks for the replayed tool-pair shapes of the standalone probe."""
import unittest

from tools import probe_standalone_outputs as probe


class ReplayedPairShapeTests(unittest.TestCase):
    def test_strict_rows_keep_each_pair_type_call_id_and_marker(self):
        for model in ('xiaomi/mimo-v2.6-pro', 'meta/muse-spark-1.3-contributor'):
            for shape in ('custom_pair', 'apply_patch_pair'):
                with self.subTest(model=model, shape=shape):
                    probe.prepare_offline(model, shape)


if __name__ == '__main__':
    unittest.main()
