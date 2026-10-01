"""Private client environment for synthetic Claude probes, never owner settings."""
import os
import tempfile


def environment(work, base_url, token, effort=None, overrides=None):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('ANTHROPIC_', 'CLAUDE_', '_CLAUDE_'))
           and key not in ('ENABLE_TOOL_SEARCH', 'MAX_THINKING_TOKENS')}
    env.update(overrides or {})
    env.update(ANTHROPIC_BASE_URL=base_url, ANTHROPIC_AUTH_TOKEN=token,
               CLAUDE_CONFIG_DIR=tempfile.mkdtemp(prefix='config.', dir=work),
               CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY='false',
               CLAUDE_CODE_MAX_RETRIES='0', CLAUDE_CODE_RETRY_WATCHDOG='0',
               CLAUDE_CODE_MAX_OUTPUT_TOKENS='2048', CLAUDE_CODE_MAX_TURNS='3',
               CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION='false')
    if effort is not None:
        env['CLAUDE_CODE_EFFORT_LEVEL'] = effort
    return env
