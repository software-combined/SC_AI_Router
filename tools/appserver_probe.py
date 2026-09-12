"""One JSON-RPC-over-stdio harness for the app-server probe tools.

`probe_codex_runtime.py`, `probe_context_budget.py` and `probe_agent_handoffs.py`
previously re-implemented the same spawn/drain/read/send/rpc loop. This module
owns that wire plumbing; the probes stay thin scenario drivers over it and keep
their request payloads, event filters, output fields, exit codes and timeouts.

Probe-specific policy (scrub mode choice, timeout values, stderr destination,
per-event reporting) stays in the probe via explicit constructor arguments and
the `on_event` hook. The class never decides probe policy by itself.

Signatures (`__init__`, `rpc`, `turn`, `close`) are stable: plan 145 builds its
capability-claim probe legs on this client.
"""
import json
import os
import queue
import re
import signal
import subprocess
import threading
import time

# Env-scrub policies, named for the probe whose behaviour each preserves.
AMBIENT = 'ambient'
CONTEXT_BUDGET = 'context_budget'
AGENT_HANDOFFS = 'agent_handoffs'


def scrub_env(env, mode, inject=None):
    """Scrub a copy of `env` per `mode`, preserving each probe's behaviour.

    `ambient` passes the environment through (probe_codex_runtime).
    `context_budget` strips `OPENAI_`/`CODEX_`/`CHATGPT_` keys, then sets
    `CODEX_HOME`, `OPENAI_API_KEY` and `OPENAI_BASE_URL` in that order
    (probe_context_budget); the caller supplies those values through
    `inject`, since the shared module must not invent credentials or URLs.
    `agent_handoffs` strips any key containing `API_KEY`/`TOKEN`/`SECRET`/
    `AUTH`, then sets `CODEX_HOME` (probe_agent_handoffs).
    """
    cleaned = dict(env)
    if mode == AMBIENT:
        return cleaned
    if mode == CONTEXT_BUDGET:
        for key in [k for k in cleaned
                    if k.startswith(('OPENAI_', 'CODEX_', 'CHATGPT_'))]:
            del cleaned[key]
        for key in ('CODEX_HOME', 'OPENAI_API_KEY', 'OPENAI_BASE_URL'):
            if inject and key in inject:
                cleaned[key] = inject[key]
        return cleaned
    if mode == AGENT_HANDOFFS:
        for key in [k for k in cleaned
                    if any(word in k.upper()
                           for word in ('API_KEY', 'TOKEN', 'SECRET', 'AUTH'))]:
            del cleaned[key]
        if inject and 'CODEX_HOME' in inject:
            cleaned['CODEX_HOME'] = inject['CODEX_HOME']
        return cleaned
    raise ValueError('unknown scrub mode: ' + str(mode))


class AppServer:
    """A Codex app-server child reached over JSON-RPC on stdio."""

    def __init__(self, command, cwd, env, stderr=None, on_event=None,
                 start_new_session=False, kill_group=False,
                 rpc_timeout=30.0, eof_detail=None, strict_lines=False):
        """Spawn `command` with `cwd`/`env` and start the reader threads.

    `stderr` selects the child's stderr: `subprocess.PIPE` (drained
        silently, the probe_codex_runtime shape), an open file object the
        child writes to directly (the probe_context_budget client.log
        shape), or None for inherited stderr. `kill_group` mirrors the
        probe_context_budget shape (process-group SIGTERM on POSIX via
        `start_new_session`); the default plain `terminate()` matches
        probe_codex_runtime and probe_agent_handoffs. `on_event` is an
        optional hook called with every event dequeued from stdout, so a
        probe can report or record probe-specific facts without the
        shared class knowing probe policy. `eof_detail` is an optional
        zero-argument callable returning extra text for the EOF error.
        """
        self._on_event = on_event
        self._rpc_timeout = rpc_timeout
        self._eof_detail = eof_detail
        self._strict_lines = strict_lines
        self._kill_group = kill_group and os.name != 'nt'
        self._sequence = 0
        self._stderr_file = None
        if stderr is None:
            child_stderr = None
        elif stderr == subprocess.PIPE:
            child_stderr = subprocess.PIPE
        else:
            child_stderr = stderr
            self._stderr_file = stderr
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=child_stderr, text=True, cwd=cwd, env=env,
            start_new_session=start_new_session)
        self.events = queue.Queue()
        if child_stderr == subprocess.PIPE:
            threading.Thread(target=self._drain_stderr, daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()

    def _drain_stderr(self):
        # Drain diagnostics without logging potentially secret-bearing URLs.
        for _ in self.process.stderr:
            pass

    def _read(self):
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                if self._strict_lines:
                    self.events.put({'parse_error': True})
        self.events.put({'eof': True})

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def next_event(self, deadline=None, timeout=None):
        """Return the next stdout event, raising on EOF or on timeout.

        `deadline` is an absolute `time.monotonic()` value (the shape the
        probes use today); `timeout` is a relative number of seconds for
        callers without a shared deadline. Timeout raises `queue.Empty`.
        """
        if deadline is None:
            if timeout is None:
                event = self.events.get()
            else:
                event = self.events.get(timeout=timeout)
        else:
            event = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
        if self._on_event is not None:
            self._on_event(event)
        if 'eof' in event:
            detail = self._eof_detail() if self._eof_detail else ''
            raise RuntimeError('App server exited' + (': ' + detail if detail else ''))
        if event.get('parse_error'):
            raise RuntimeError('App server wrote a malformed stdout line')
        return event

    def rpc(self, method, params, timeout=None):
        """Send a request and return its result.

        `timeout` overrides the constructor `rpc_timeout` for this call
        (pass the probe's remaining global deadline to keep the current
        wait-until-deadline shape). An error reply raises RuntimeError;
        a probe that maps reply errors to its own exception keeps a local
        `send`/`next_event` loop instead (probe_agent_handoffs does this
        to preserve its ValueError contract).
        """
        self._sequence += 1
        ident = self._sequence
        self.send({'id': ident, 'method': method, 'params': params})
        deadline = time.monotonic() + (self._rpc_timeout if timeout is None else timeout)
        while True:
            event = self.next_event(deadline=deadline)
            if event.get('id') == ident and 'method' not in event:
                if 'error' in event:
                    raise RuntimeError(str(event['error']))
                return event['result']

    def turn(self, thread, text, timeout=40.0, expect_error=False, marker=None,
             expect_error_code='contextWindowExceeded', payload=None):
        """Start a text turn and return `(answer, turn)` on completion.

        Collects `agentMessage` text and applies the completed/failed
        contract: raises on `error` events unless `expect_error` is set,
        in which case the turn must fail with `expect_error_code` (the
        probe_context_budget shape). When `marker` is given, a completed
        turn must retain it in the answer. `payload` supplies extra
        `turn/start` fields (model, effort, attachments); the default
        sends the context-budget shape. The caller owns policy: the class
        only applies the contract it is handed.
        """
        request = {'threadId': thread, 'input': [
            {'type': 'text', 'text': text, 'text_elements': []}]}
        request.update(payload or {})
        self.rpc('turn/start', request)
        deadline = time.monotonic() + timeout
        answer = ''
        while True:
            event = self.next_event(deadline=deadline)
            if event.get('method') == 'error':
                if not expect_error:
                    raise RuntimeError(re.sub(r'https?://\S+', '[URL]', str(event['params'])))
            if event.get('method') == 'item/completed':
                item = event['params']['item']
                if item.get('type') == 'agentMessage':
                    answer = item.get('text', '')
            if event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                if expect_error:
                    assert turn['status'] == 'failed', 'expected context exhaustion'
                    assert turn['error']['codexErrorInfo'] == expect_error_code, turn['error']
                else:
                    assert turn['status'] == 'completed', str(turn.get('error'))
                    if marker is not None:
                        assert marker in answer, 'client did not retain the synthetic marker'
                return answer, turn

    def close(self):
        """Terminate the child, waiting 5s before killing it (probe shape).

        With `kill_group`, POSIX sends SIGTERM to the whole process group
        (the probe_context_budget shape, which spawns with
        `start_new_session`); otherwise plain `terminate()` (the
        probe_codex_runtime / probe_agent_handoffs shape). Either way the
        child's stdin and any caller-supplied stderr file are closed; the
        reader threads own stdout/stderr and exit with the process.
        """
        if self.process is None:
            return
        process, self.process = self.process, None
        try:
            if self._kill_group:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    process.terminate()
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        finally:
            # Close only stdin: the daemon reader/drain threads own stdout and
            # stderr, and closing those here blocks on their lock while a
            # descendant still holds the write end (a hang the probes must not
            # inherit). The threads exit with the process.
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            if self._stderr_file is not None:
                try:
                    self._stderr_file.close()
                except (OSError, ValueError):
                    pass
                self._stderr_file = None
