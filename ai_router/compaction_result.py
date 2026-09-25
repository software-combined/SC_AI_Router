"""Validate a Responses payload returned by the compaction summarizer."""


class IncompleteSummary(ValueError):
    """A summary was cut off or emptied by the output-token ceiling."""


def _details(data):
    details = data.get('incomplete_details')
    if details is None:
        return None
    if not isinstance(details, dict):
        raise ValueError('Compaction incomplete details malformed')
    reason = details.get('reason')
    if reason is not None and not isinstance(reason, str):
        raise ValueError('Compaction incomplete reason malformed')
    return reason


def _status(data):
    status = data.get('status')
    if status is not None and not isinstance(status, str):
        raise ValueError('Compaction summary status malformed')
    return status


def _text(value, message):
    if value is not None and not isinstance(value, str):
        raise ValueError(message)
    return value if isinstance(value, str) and value else None


def _output_text(data, allow_incomplete_item=False):
    output = data.get('output')
    if not isinstance(output, list):
        raise ValueError('Summarizer response has no output list')
    texts = []
    for item in output:
        if not isinstance(item, dict):
            raise ValueError('Summarizer output item is not an object')
        if item.get('error') is not None:
            raise ValueError('Summarizer output item contains an error')
        item_status = item.get('status')
        if item_status not in (None, 'completed') and not (
                item_status == 'incomplete' and allow_incomplete_item):
            raise ValueError('Summarizer output item is not completed')
        if item.get('type') == 'message':
            content = item.get('content', [])
            if not isinstance(content, list):
                raise ValueError('Summarizer message content malformed')
            for block in content:
                if not isinstance(block, dict):
                    raise ValueError('Summarizer content block is not an object')
                if block.get('type') in ('output_text', 'text'):
                    text = _text(block.get('text'),
                                 'Summarizer output text malformed')
                    if text:
                        texts.append(text)
        elif item.get('type') == 'output_text':
            text = _text(item.get('text'), 'Summarizer output text malformed')
            if text:
                texts.append(text)
    summary = '\n'.join(texts).strip()
    if not summary and not allow_incomplete_item:
        raise ValueError('Compaction summary empty; retry compaction.')
    return summary


def extract_summary(status, data, expected_model=None):
    """Return valid summary text or a typed, fail-closed validation error."""
    # The provider must return a successful Responses envelope; the router's
    # own 409 is the fail-closed result after all summary attempts fail.
    if status != 200:
        raise OSError('Summarizer upstream failed')
    if not isinstance(data, dict):
        raise ValueError('Summarizer response is not an object')
    if data.get('error') is not None:
        raise ValueError('Summarizer response contains an error')
    if expected_model is not None and data.get('model') != expected_model:
        raise ValueError('Summarizer served unexpected model')
    payload_status = _status(data)
    reason = _details(data)
    retryable = reason == 'max_output_tokens' and payload_status in (None, 'incomplete')
    summary = _output_text(data, allow_incomplete_item=retryable)
    if retryable:
        raise IncompleteSummary(
            'Compaction summary incomplete (max_output_tokens); retry compaction.')
    if payload_status is not None and payload_status != 'completed':
        raise ValueError('Compaction summary is not completed')
    if reason:
        raise ValueError('Compaction summary is incomplete')
    return summary
