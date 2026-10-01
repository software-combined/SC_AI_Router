"""Content-free tool and identity facts from a synthetic Claude probe stream."""
import json
from pathlib import Path

STUB_TOOL = 'mcp__stubtools__tool_000'


def identity(expected_model, report):
    served = report.get('served') or []
    if not served:
        return 'unverified'
    return 'matched' if all(item == expected_model for item in served) else 'mismatched'


def accepted(read_count, markers, report, expected_model, deferred=False):
    answer = report.get('result') or ''
    if (report.get('is_error') or report.get('tool_errors')
            or identity(expected_model, report) == 'mismatched'
            or not all(item in answer for item in markers)):
        return False
    if deferred:
        return (report.get('tool_names') == ['ToolSearch', STUB_TOOL]
                and bool(report.get('deferred_sequence'))
                and bool(report.get('tool_result_ids_match')))
    if read_count == 1:
        return True
    return (report.get('read_calls') == read_count
            and report.get('tool_calls') == read_count
            and report.get('read_paths') == ['probe-1.txt', 'probe-2.txt']
            and bool(report.get('sequential_reads'))
            and bool(report.get('tool_result_ids_match')))


def _content(event):
    message = event.get('message') if isinstance(event.get('message'), dict) else {}
    content = message.get('content')
    return content if isinstance(content, list) else []


def stream_report(stdout):
    served, result = set(), {}
    read_paths, read_steps, tool_steps = [], [], []
    call_ids, result_ids, names = [], [], []
    tool_errors = False
    for step, line in enumerate(stdout.splitlines()):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'assistant':
            message = event.get('message') or {}
            if message.get('model'):
                served.add(message['model'])
            for part in _content(event):
                if not isinstance(part, dict) or part.get('type') != 'tool_use':
                    continue
                call_ids.append(part.get('id'))
                names.append(part.get('name'))
                tool_steps.append((step, len(result_ids)))
                if part.get('name') != 'Read':
                    continue
                inputs = part.get('input') if isinstance(part.get('input'), dict) else {}
                path = inputs.get('file_path') or inputs.get('path')
                if path:
                    name = Path(str(path)).name
                    read_paths.append(name)
                    read_steps.append((step, len(result_ids), name))
        elif event.get('type') == 'user':
            for part in _content(event):
                if isinstance(part, dict) and part.get('type') == 'tool_result':
                    result_ids.append(part.get('tool_use_id'))
                    tool_errors = tool_errors or bool(part.get('is_error'))
        elif event.get('type') == 'result':
            result = event
    sequential_reads = any(
        later[0] > earlier[0] and later[1] > earlier[1]
        and {earlier[2], later[2]} == {'probe-1.txt', 'probe-2.txt'}
        for earlier, later in zip(read_steps, read_steps[1:]))
    paired = (len(call_ids) == len(result_ids)
              and all(isinstance(identifier, str) and identifier for identifier in call_ids)
              and len(set(call_ids)) == len(call_ids) and result_ids == call_ids)
    result.update(tool_calls=len(call_ids), read_calls=names.count('Read'),
                  tool_names=names, tool_errors=tool_errors,
                  deferred_sequence=len(tool_steps) == 2 and tool_steps[1][1] > tool_steps[0][1],
                  read_paths=read_paths, sequential_reads=sequential_reads,
                  tool_result_ids_match=paired, served=sorted(served))
    return result
