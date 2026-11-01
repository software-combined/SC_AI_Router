"""Run the offline suite in one process or two bounded, isolated CI workers."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def leaves(suite, *, parallel=False):
    if isinstance(suite, unittest.TestSuite):
        if parallel and type(suite) is not unittest.TestSuite:
            raise ValueError('parallel execution requires standard unittest suites')
        for test in suite:
            yield from leaves(test, parallel=parallel)
    else:
        yield suite


def partition(cases, worker):
    boundaries = [i for i in range(1, len(cases))
                  if type(cases[i - 1]).__module__ != type(cases[i]).__module__]
    if not boundaries:
        raise ValueError('two workers require at least two module runs')
    cut = min(boundaries, key=lambda i: (abs(len(cases) - 2 * i), i))
    return cases[:cut] if worker == 0 else cases[cut:]


class RecordingResult(unittest.TextTestResult):
    """Observe public result callbacks without changing unittest execution."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.events = []
        self.current = None
        self.finished = 0

    def startTest(self, test):
        self.current = (test, {'id': test.id(), 'outcome': 'incomplete'})
        self.cases.append(self.current[1])
        super().startTest(test)

    def stopTest(self, test):
        self.finished += 1
        self.current = None
        super().stopTest(test)

    def outcome(self, test, outcome, reason=None):
        record = {'id': test.id(), 'outcome': outcome}
        if reason is not None:
            record['reason'] = str(reason)
        if self.current is not None and test is self.current[0]:
            self.current[1].update(record)
        else:
            record['kind'] = 'subtest' if self.current is not None else 'fixture'
            self.events.append(record)
            if self.current is not None:
                self.current[1]['outcome'] = 'subtests'

    def addSuccess(self, test):
        self.outcome(test, 'passed')
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.outcome(test, 'failed')
        super().addFailure(test, err)

    def addError(self, test, err):
        self.outcome(test, 'error')
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.outcome(test, 'skipped', reason)
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.outcome(test, 'expected-failure')
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.outcome(test, 'unexpected-success')
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        outcome = 'passed' if err is None else 'failed' if issubclass(err[0], test.failureException) else 'error'
        self.outcome(subtest, outcome)
        super().addSubTest(test, subtest, err)


class RecordingRunner(unittest.TextTestRunner):
    resultclass = RecordingResult


class Program(unittest.TestProgram):
    def __init__(self, args, worker):
        self.worker = worker
        super().__init__(module=None, argv=['unittest', *args], exit=False,
                         testRunner=RecordingRunner)

    def runTests(self):
        cases = list(leaves(self.test, parallel=self.worker is not None))
        self.inventory = [test.id() for test in cases]
        selected = cases if self.worker is None else partition(cases, self.worker)
        self.selected_cases = selected
        self.selected = [test.id() for test in selected]
        if self.worker is not None:
            self.test = unittest.TestSuite(selected)
        super().runTests()

    def report(self):
        result = self.result
        counts = {name: len(getattr(result, name)) for name in
                  ('skipped', 'errors', 'failures', 'expectedFailures', 'unexpectedSuccesses')}
        counts['testsRun'] = result.testsRun
        missing = Counter(self.selected) - Counter(row['id'] for row in result.cases)
        fixture_skips = {row['id'] for row in result.events
                         if row['kind'] == 'fixture' and row['outcome'] == 'skipped'}
        suppressed = []
        for test in self.selected_cases:
            cls = type(test)
            fixtures = {f'setUpModule ({cls.__module__})',
                        f'setUpClass ({cls.__module__}.{cls.__qualname__})'}
            if missing[test.id()] and fixtures & fixture_skips:
                suppressed.append(test.id())
                missing[test.id()] -= 1
        complete = (bool(self.inventory) and result.wasSuccessful() and not result.shouldStop
                    and result.finished == len(result.cases)
                    and Counter(row['id'] for row in result.cases) + Counter(suppressed) == Counter(self.selected)
                    and all(row['outcome'] != 'incomplete' for row in result.cases))
        return {'complete': complete, 'inventory': self.inventory, 'selected': self.selected,
                'fixture_skipped': suppressed,
                'cases': result.cases, 'events': result.events, 'summary': counts}


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def stop_workers(processes):
    """Stop whole owned process groups, including surviving grandchildren."""
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in processes:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_workers(args):
    interrupted = False

    def interrupt(_signal, _frame):
        nonlocal interrupted
        interrupted = True

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    processes, streams, reports = [], [], []
    try:
        with tempfile.TemporaryDirectory(prefix='ci-unittest-') as temporary:
            root = Path(temporary)
            try:
                for index in range(2):
                    stream = (root / f'{index}.log').open('w+', encoding='utf-8')
                    streams.append(stream)
                    command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(index),
                               '--report', str(root / f'{index}.json'), '--', *args.tests]
                    processes.append(subprocess.Popen(command, stdout=stream, stderr=stream,
                                                      start_new_session=True))
                while not interrupted:
                    codes = [process.poll() for process in processes]
                    if all(code is not None for code in codes) or any(code not in (None, 0) for code in codes):
                        break
                    time.sleep(0.05)
            finally:
                stop_workers(processes)
                for index, stream in enumerate(streams):
                    stream.seek(0)
                    print(f'\nWorker {index + 1}:\n{stream.read()}', flush=True)
                    stream.close()
                    path = root / f'{index}.json'
                    if path.exists():
                        reports.append(json.loads(path.read_text(encoding='utf-8')))
            complete = (not interrupted and len(reports) == 2
                        and all(process.returncode == 0 for process in processes)
                        and all(report['complete'] for report in reports)
                        and reports[0]['inventory'] == reports[1]['inventory']
                        and Counter(item for report in reports for item in report['selected'])
                        == Counter(reports[0]['inventory']))
            return {'complete': complete, 'interrupted': interrupted,
                    'exit_codes': [process.returncode for process in processes],
                    'inventory': reports[0]['inventory'] if reports else [],
                    'cases': [row for report in reports for row in report['cases']],
                    'events': [row for report in reports for row in report['events']],
                    'fixture_skipped': [item for report in reports for item in report['fixture_skipped']],
                    'summary': dict(sum((Counter(report['summary']) for report in reports), Counter())),
                    'workers': reports}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--worker', type=int, choices=(0, 1), help=argparse.SUPPRESS)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('tests', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.tests[:1] == ['--']:
        args.tests.pop(0)
    if args.workers == 2 and os.name != 'posix':
        parser.error('two workers require POSIX process groups')
    if args.workers == 2:
        report = run_workers(args)
    else:
        report = Program(args.tests, args.worker).report()
    report.update({'python': sys.version, 'platform': sys.platform})
    write_report(args.report, report)
    print('CI unittest:', json.dumps({'complete': report['complete'], **report['summary']}))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
