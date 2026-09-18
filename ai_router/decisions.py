"""Typed judgments from Jev; not a chat client, planner or picker model.

Usage rules (rationale and evidence: docs/architecture.md, docs/compatibility.md):
- Keep state small: named task facts, retained evidence and candidate facts,
  not secrets or raw transcripts. Text in state is evidence, not authority.
- Jev never sees question ids. Each instruction must name its backticked
  state path; one question asks one narrow judgment.
- Batch independent questions sharing one state into one ask; chain calls
  only when the next question needs new information.
- noul is the probability a proposition is true, not importance. Choice
  confidence measures distribution concentration, not the chosen probability.
  Never multiply correlated judgments.
- Jev proposes; deterministic code decides. Start in shadow mode; destructive
  behavior stays off until measured. An error keeps today's behavior.
- One attempt, no retries or fallback. A 5xx is upstream_error, not a verdict
  on the task or permission to retry. Consumers own budgets and safe fallback.
- Pin a verified snapshot in provider_defs; an override needs its own evidence
  so an alias change cannot silently shift behavior.

This module owns wire validation only and is off the request path. Every
upstream fact comes from provider_defs. The caller supplies the inference key;
it travels only in Authorization, never a URL, message or log.
"""
import http.client
import json
import urllib.error
import urllib.request

from . import provider_defs

QUESTION_TYPES = ('noul', 'choice')
# The endpoint also accepts `score`; it stays refused here until one live
# probe shows its answer envelope. Guessing a wire shape is worse than no.
UNVERIFIED_TYPES = ('score',)

MAX_BODY = 64 * 1024
MAX_RESPONSE = 1 << 18
TIMEOUT_S = 5.0
# Every refusal this client can raise, so callers and logs share one set.
ERROR_CODES = ('no_endpoint', 'missing_key', 'bad_request', 'bad_question',
               'unsupported_question', 'request_too_large',
               'response_too_large', 'unauthorized', 'refused', 'upstream_error',
               'unreachable',
               'malformed_response', 'incomplete_answers', 'unknown_answer')


class DecisionError(ValueError):
    """One refusal from this client, carrying a code from ERROR_CODES."""

    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


def question(kind, instructions, criteria=None):
    """One atomic judgment; name state fields in instructions, not just its id.

    Jev does not see question ids. Use explicit backticked state paths and
    batch independent questions sharing that state in one `ask` call; chain
    only for new information. Apply the module's usage rules before sending.
    """
    if kind in UNVERIFIED_TYPES:
        raise DecisionError('unsupported_question',
                            'answers of this type are not verified yet')
    if kind not in QUESTION_TYPES:
        raise DecisionError('bad_question', 'unknown question type')
    if not isinstance(instructions, str) or not instructions.strip():
        raise DecisionError('bad_question', 'a question needs instructions')
    body = {'type': kind, 'instructions': instructions.strip()}
    if kind == 'choice':
        if not isinstance(criteria, dict) or not criteria:
            raise DecisionError('bad_question', 'a choice question needs criteria')
        for key, text in criteria.items():
            if not isinstance(key, str) or not key:
                raise DecisionError('bad_question', 'choice criteria need names')
            if not isinstance(text, str) or not text.strip():
                raise DecisionError('bad_question',
                                    'choice criteria need text')
        body['criteria'] = dict(criteria)
    elif criteria is not None:
        raise DecisionError('bad_question', 'only a choice question takes criteria')
    return body


def ask(state, questions, defn=None, model=None, key=None, timeout=TIMEOUT_S,
        _urlopen=None):
    """Answers keyed by question id, or DecisionError.

    `state` is what the model reasons over (a string, object or list, as the
    endpoint accepts); `questions` maps our own id to a `question()`. Each
    answer comes back as `{'type', 'value', 'confidence', 'probabilities'}`:
    a `noul` value is the probability the proposition is true, not an
    importance score. A `choice` value is one of the criteria names; its
    confidence describes distribution concentration, not that option's
    probability. Nothing else from the envelope is exposed.
    `timeout` is a socket-operation limit in (0, 5] seconds, not a total
    deadline; a consumer needing bounded wall time must bound its own wait.
    Apply the module's usage rules; this call never retries or switches models.
    """
    defn = defn or provider_defs.OPENROUTER
    model = defn.decisions_model if model is None else model
    if not defn.decisions_path or model is None:
        raise DecisionError('no_endpoint',
                            'the provider serves no decisions endpoint')
    if (not isinstance(key, str) or not key
            or any(not 33 <= ord(char) <= 126 for char in key)):
        raise DecisionError('missing_key', 'no usable key for the decisions endpoint')
    if (not isinstance(model, str) or not model.strip()
            or not isinstance(state, (str, dict, list))
            or not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not 0 < timeout <= TIMEOUT_S):
        raise DecisionError('bad_request', 'invalid state, model or timeout')
    if not isinstance(questions, dict) or not questions:
        raise DecisionError('bad_question', 'at least one question is required')
    # Re-validate and normalize what is sent, so a half-built question can
    # never reach the wire and the answer is judged against the exact body.
    checked = {qid: _checked(qid, asked) for qid, asked in questions.items()}
    try:
        body = json.dumps({'model': model, 'state': state, 'questions': checked},
                          allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        raise DecisionError('bad_request', 'the request is not valid JSON') from None
    if len(body) > MAX_BODY:
        raise DecisionError('request_too_large',
                            f'the request is over {MAX_BODY} bytes')
    request = urllib.request.Request(
        'https://' + defn.host + defn.decisions_path, data=body,
        headers={'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json'})
    opener = _urlopen or urllib.request.build_opener(_NoRedirect()).open
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()  # Never read or echo an upstream refusal body.
        if 500 <= status < 600:
            code, action = 'upstream_error', 'failed upstream'
        else:
            code = 'unauthorized' if status in (401, 403) else 'refused'
            action = 'refused the request'
        raise DecisionError(code,
                            f'the decisions endpoint {action} ({status})',
                            status) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise DecisionError('unreachable',
                            'the decisions endpoint did not answer') from None
    if len(raw) > MAX_RESPONSE:
        raise DecisionError('response_too_large',
                            f'the answer is over {MAX_RESPONSE} bytes')
    try:
        payload = json.loads(raw.decode(), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise DecisionError('malformed_response',
                            'the decisions endpoint answered with no JSON') from None
    return _answers(payload, checked)


def _checked(qid, asked):
    """The normalized question body for one id, or DecisionError."""
    if not isinstance(qid, str) or not qid:
        raise DecisionError('bad_question', 'question ids must be text')
    if not isinstance(asked, dict):
        raise DecisionError('bad_question',
                            'a question is not a question() body')
    return question(asked.get('type'), asked.get('instructions'),
                    asked.get('criteria'))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        # Even a same-host redirect is outside the verified endpoint contract.
        raise urllib.error.HTTPError(req.full_url, code, 'redirect refused', {}, fp)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate JSON member')
        result[name] = value
    return result


def _answers(payload, questions):
    """Normalized answers, or DecisionError when the shape is not ours."""
    rows = payload.get('answers') if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        raise DecisionError('malformed_response', 'the answer carries no answers')
    if questions.keys() - rows.keys():
        raise DecisionError('incomplete_answers',
                            'the response is missing answers')
    if rows.keys() - questions.keys():
        raise DecisionError('unknown_answer',
                            'the response has answers we did not ask for')
    return {qid: _answer(questions[qid], rows[qid]) for qid in sorted(questions)}


def _answer(asked, row):
    """One normalized answer: type, value, confidence, probabilities."""
    if not isinstance(row, dict) or row.get('type') != asked['type']:
        raise DecisionError('malformed_response',
                            'the answer type is not the question type')
    if asked['type'] == 'noul':
        value = row.get('noul')
        if not _number(value):
            raise DecisionError('malformed_response',
                                'no confidence between 0 and 1')
        return {'type': 'noul', 'value': float(value),
                'confidence': None, 'probabilities': None}
    chosen = row.get('choice')
    if not isinstance(chosen, str) or chosen not in asked['criteria']:
        raise DecisionError('malformed_response',
                            'the choice is not one of the criteria')
    probabilities = row.get('probabilities')
    if (not isinstance(probabilities, dict)
            or probabilities.keys() != asked['criteria'].keys()
            or not all(_number(share) for share in probabilities.values())):
        raise DecisionError('malformed_response',
                            'probabilities must cover exactly the asked criteria')
    if probabilities[chosen] < max(probabilities.values()):
        raise DecisionError('malformed_response',
                            'the choice is not a highest-probability option')
    confidence = row.get('confidence')
    if not _number(confidence):
        raise DecisionError('malformed_response',
                            'confidence is not a number between 0 and 1')
    return {'type': 'choice', 'value': chosen,
            'confidence': float(confidence), 'probabilities': dict(probabilities)}


def _number(value):
    """True for a JSON number inside 0..1; bools are not numbers here."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 1)
