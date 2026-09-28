"""Synthetic route evidence for offline candidate-gate regressions."""
from ai_router import candidate_evidence as evidence, provider_defs
from ai_router.clients.registry import CLIENTS


def proof(row):
    row = evidence.model(row)
    record = evidence.binding(row)
    record['routes'] = [
        {'protocol': client.protocol, 'client': client.id, 'client_version': '1.2.3',
         'requested_effort': row.default_reasoning,
         'served_models': [{'value': row.upstream_id or row.slug,
                            'source': 'response.model' if client.id == 'codex' else 'message.model'}],
         'served_efforts': [], 'calls': 2, 'conformance': 'pass', 'result': 'pass'}
        for client in CLIENTS if provider_defs.get(row.provider).serves(client.protocol)]
    return record
