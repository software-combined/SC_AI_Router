"""HTML for the loopback key page: the no-GUI fallback for Plan 139.

The native popup (`ai_router.key_prompt`) is the primary first-run surface;
this page stays for hosts with no dialog tool, so the setup protocol keeps a
single HTTP contract. Inline style only: the page must not fetch anything.
"""
import html

# Client-aware closing line, shared with the native popup's confirmation.
RESTART = {'codex': 'Restart Codex',
           'claude': 'Restart Claude Code',
           'both': 'Quit and reopen Codex, and restart Claude Code',
           'none': 'Restart your AI client'}

# Executive light theme lifted from SC_360 tokens (packages/ui/src/tokens.css): slate-50
# canvas, white card, blue-600 primary, slate-200 hairlines, 0.75rem radius, 2.75rem
# controls. Inline only: a loopback first-run page fetches no external asset or font.
_STYLE = '''*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2.5rem 1rem;background:hsl(210,40%,98%);color:hsl(222,47%,11%);font:1rem/1.55 Inter,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
main{width:100%;max-width:32rem;background:#fff;border:1px solid hsl(214,32%,91%);border-radius:.75rem;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.05),0 10px 24px -12px rgba(15,23,42,.15)}
h1{margin:0;padding:1.125rem 1.5rem;border-bottom:1px solid hsl(214,32%,91%);letter-spacing:-.025em;font:500 1.0625rem/1.4 "Space Grotesk",Inter,Arial,sans-serif}
.b{padding:1.5rem}
p{margin:0 0 1.5rem;color:hsl(215,16%,45%);font-size:.9375rem}
label.f{display:block;margin-bottom:.5rem;font-size:.8125rem;font-weight:500}
input[type=password]{width:100%;min-height:2.75rem;padding:0 .75rem;background:#fff;border:1px solid hsl(214,32%,91%);border-radius:.5rem;color:inherit;font:inherit}
fieldset{margin:1.25rem 0 0;padding:0;border:0}
legend{padding:0 0 .5rem;font-size:.8125rem;font-weight:500}
.o{display:flex;gap:.625rem;align-items:flex-start;margin-bottom:.5rem;padding:.75rem;border:1px solid hsl(214,32%,91%);border-radius:.5rem;font-size:.9375rem;cursor:pointer}
.o:hover{background:hsl(214,100%,97%);border-color:hsl(221,83%,53%)}
.o em{display:block;margin-top:.125rem;color:hsl(215,16%,45%);font-size:.8125rem;font-style:normal}
input[type=radio]{margin:.2rem 0 0;accent-color:hsl(221,83%,53%)}
button{margin-top:1.5rem;width:100%;min-height:2.75rem;padding:0 1rem;border:0;border-radius:.5rem;background:hsl(221,83%,53%);color:#fff;cursor:pointer;font:500 .9375rem/1 Inter,Arial,sans-serif}
button:hover{background:hsl(221,83%,47%)}
:focus-visible{outline:2px solid hsl(221,83%,53%);outline-offset:2px}
.e{margin:0 0 1.25rem;padding:.75rem 1rem;border:1px solid hsl(0,72%,85%);border-radius:.5rem;background:hsl(0,86%,97%);color:hsl(0,72%,41%);font-size:.875rem}
dl{display:grid;grid-template-columns:auto 1fr;gap:.5rem 1rem;margin:0 0 1.5rem;font-size:.9375rem}
dt{color:hsl(215,16%,45%)}
dd{margin:0;font-weight:500;word-break:break-word}'''


def _page(title, body):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{_STYLE}</style>'
            f'</head><body><main><h1>{html.escape(title)}</h1>'
            f'<div class="b">{body}</div></main></body></html>').encode()


def not_found():
    return _page('Not found', '<p>Unknown or expired setup link.</p>')


def form(nonce, error=None):
    complaint = f'<p class="e"><strong>Error:</strong> {html.escape(error)}</p>' if error else ''
    return _page('Connect OpenRouter', complaint + f'''<p>Paste an OpenRouter key. It is validated
before anything is stored, and kept in an owner-only file the router reads at request time.</p>
<form method="post" action="./{html.escape(nonce, quote=True)}">
<label class="f" for="key">OpenRouter key</label>
<input id="key" type="password" name="key" autocomplete="off" placeholder="sk-or-v1-...">
<fieldset><legend>ChatGPT subscription</legend>
<label class="o"><input type="radio" name="mode" value="subscription" checked><span>I have one
<em>Route OpenAI models on the subscription</em></span></label>
<label class="o"><input type="radio" name="mode" value="none"><span>No subscription
<em>OpenRouter models only</em></span></label>
</fieldset>
<fieldset><legend>Starter instructions</legend>
<label class="o"><input type="radio" name="profile" value="general" checked><span>Everyday help
<em>Everyday help: careful, brief, plain language</em></span></label>
<label class="o"><input type="radio" name="profile" value="dev"><span>Coding help
<em>Coding help: read first, small verified changes, tests</em></span></label>
</fieldset>
<p style="margin:1rem 0 0">The starter is installed only when no global
instructions file exists yet. An existing file is never overwritten.</p>
<button type="submit">Save and connect</button></form>''')


def remaining(limit, usage):
    """Human remaining credit for the confirmation surfaces."""
    try:
        return 'unlimited' if limit is None else str(limit - (usage or 0))
    except TypeError:
        return 'unknown'


def done(label, limit, usage, mode, starter, clients='codex'):
    return _page('Connected', f'''<p>Your key is validated and stored.</p>
<dl><dt>Key</dt><dd>{html.escape(str(label))}</dd>
<dt>Remaining credit</dt><dd>{html.escape(remaining(limit, usage))}</dd>
<dt>Mode</dt><dd>{html.escape(mode)}</dd>
<dt>Starter</dt><dd>{html.escape(starter)}</dd></dl>
<p>You can close this window and {html.escape(RESTART.get(clients, RESTART['codex']))}.</p>''')
