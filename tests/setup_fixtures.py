"""Isolate key-window tests from live provider lists and earlier snapshots."""
from unittest import mock
from ai_router import availability


def offline_availability(test):
    test.enterContext(mock.patch.object(availability, '_SNAPSHOTS', {}))
    test.enterContext(mock.patch.object(availability, '_HAD_SNAPSHOT', set()))
    test.enterContext(mock.patch.object(availability, 'fetch',
                                       side_effect=OSError('offline fixture')))
