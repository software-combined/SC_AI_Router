"""Policy scans with one owner (Plan 134).

Implements the two greps that used to be inline shell in
`.github/workflows/check.yml`, so they run identically locally
(`python3.14 tools/check_policy_scans.py`) and in CI:

- request-cap scan: the cap was removed by owner decision
  (`docs/operations.md`); any reintroduction fails.
- secrets scan: OpenRouter keys and bearer tokens must never be committed.
- dialect scan: an upstream dialect comparison reads the constant the
  definition table exports, never a raw string (Plan 152).

Both scans read files as bytes, matching historical `grep -r` behaviour
on text and binary files alike. This script necessarily names the
request-cap pattern, so it excludes its own path from that scan.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUEST_CAP_RE = re.compile(rb'request_cap|DEFAULT_REQUEST_CAP')
SECRET_RE = re.compile(rb'sk-or-v1-[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{30,}')
# Historical `grep -r` matched any file, text or binary; nothing here may be
# narrower than the CI gate it replaced, or a committed key can hide in a
# file the scan never opened.
SCAN_ALL = ('.',)
# A same-repo local action cannot run before checkout, so the composite owns
# the pin and every workflow must reach setup through it (Plan 134).
SETUP_PIN_RE = re.compile(rb'actions/setup-python@[0-9a-f]{40}')
# A real step, not a comment or a substring elsewhere: either the inline
# `- uses:` form (optionally with a trailing comment) or a two-line step
# whose `uses:` line sits at step indent.
# `\r?` before the line end keeps the match on CRLF checkouts (a Windows
# developer with core.autocrlf, or a fixture written in text mode) as well
# as on the LF files CI reads.
SETUP_STEP_RE = re.compile(
    rb'(?m)^[ \t]*(?:-[ \t]+)?uses: \./\.github/actions/setup'
    rb'(?:[ \t]*#.*)?[ \t]*\r?$')
# An AWS account id inside an ARN, or a bucket-shaped name carrying one, is a
# publication identifier (Plan 160): it belongs in repository variables, so a
# copy returning to the tree fails here. Neither pattern spells an account id,
# so this file needs no self-exclusion; `plans/` is gitignored working notes
# that never ship.
ACCOUNT_ARN_RE = re.compile(rb'arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:')
ACCOUNT_BUCKET_RE = re.compile(rb'\b[a-z0-9][a-z0-9.-]{2,}-\d{12}-[a-z0-9-]+')
# A dialect comparison against a raw string (Plan 152): `provider_defs` owns
# the dialect, so a call site compares the constant it exports. Only the
# comparison is forbidden, not the table's own definitions. Every comparison
# operator counts, in either order: a gate that only knows `==` misses the
# `!=` and `in` forms of the same fork.
DIALECT_OPERATOR = rb'(?:==|!=|not\s+in|in)'
DIALECT_LITERAL_RE = re.compile(
    rb"""dialect\s*""" + rb'''(?:''' + DIALECT_OPERATOR + rb""")\s*[(\[]?\s*['"]"""
    rb"""|['"]\s*(?:""" + DIALECT_OPERATOR + rb""")\s*[\w.]*dialect""")
TABLE_OWNER = 'ai_router/provider_defs.py'
GITIGNORED = ('plans',)
WORKFLOWS = ('check.yml', 'release.yml')
# These exact predicates own discovery aliases and picker billing duplicates.
# The metadata predicate preserves tracking-alias labels. None is preparation
# or retry policy, and no whole module is exempt.
MODEL_ROUTING_EXCEPTIONS = {
    ('ai_router/claude.py', 'row_alias', "bare.startswith('anthropic/')"),
    ('ai_router/claude.py', 'family_tier', "alias.startswith('anthropic/claude-')"),
    ('ai_router/claude.py', 'resolve', "model.startswith('anthropic/')"),
    ('ai_router/clients/registry.py', '_listed_outside_anthropic',
     "model.slug.removeprefix('~').startswith('anthropic/')"),
    ('ai_router/model_metadata.py', 'refresh_display_name', "row['slug'].startswith('~')"),
}
MODEL_NAMES = re.compile(r'(?:^|_)(?:model|slug|alias|vendor)(?:_|$)')

SELF = Path(__file__).resolve()


def _is_derived_bytecode(path):
    """True for a __pycache__ .pyc whose source file is present."""
    if path.suffix != '.pyc' or path.parent.name != '__pycache__':
        return False
    source = path.parent.parent / (path.name.split('.')[0] + '.py')
    return source.exists()


def _iter_files(dirs):
    for dirname in dirs:
        base = ROOT / dirname
        if not base.exists():
            raise SystemExit(f'policy-scans: scanned path is missing: {dirname}')
        for path in sorted(base.rglob('*')):
            # Derived bytecode is not source (see `_is_derived_bytecode`); a
            # `.pyc` with no corresponding source is scanned.
            if _is_derived_bytecode(path):
                continue
            # Git metadata is not repository content: a commit subject can
            # carry any word, and reading the object store is wasted work.
            if '.git' in path.parts:
                continue
            if path.is_file() and not path.is_symlink():
                yield path


def check_request_cap():
    hits = [str(p.relative_to(ROOT)) for p in _iter_files(SCAN_ALL)
        if p.resolve() != SELF and REQUEST_CAP_RE.search(p.read_bytes())]
    if hits:
        print('request cap removed by decision (docs/operations.md); '
              'do not reintroduce')
        for hit in hits:
            print(f'  {hit}')
        return False
    return True


def check_secrets():
    hits = [str(p.relative_to(ROOT)) for p in _iter_files(SCAN_ALL)
            if SECRET_RE.search(p.read_bytes())]
    if hits:
        print('possible secret committed')
        for hit in hits:
            print(f'  {hit}')
        return False
    return True


def check_publication_identifiers():
    """No AWS account id or bucket name in tracked source (Plan 160)."""
    hits = []
    for path in _iter_files(SCAN_ALL):
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] in GITIGNORED:
            continue
        text = path.read_bytes()
        if ACCOUNT_ARN_RE.search(text) or ACCOUNT_BUCKET_RE.search(text):
            hits.append(str(rel))
    if hits:
        print('AWS account id or bucket name committed; it belongs in '
              'repository variables, not the tree (Plan 160)')
        for hit in hits:
            print(f'  {hit}')
        return False
    return True


def check_setup_single_owner():
    """The composite owns the setup-python pin; workflows use it."""
    action = ROOT / '.github' / 'actions' / 'setup' / 'action.yml'
    if not action.exists():
        print(f'{action.relative_to(ROOT)} is missing: no owner for the setup pin')
        return False
    pins = SETUP_PIN_RE.findall(action.read_bytes())
    ok = True
    if len(set(pins)) != 1:
        print(f'{action.relative_to(ROOT)} must pin setup-python exactly once')
        ok = False
    workflows = sorted(set((ROOT / '.github' / 'workflows').glob('*.yml'))
                       | set((ROOT / '.github' / 'workflows').glob('*.yaml')))
    for workflow in workflows:
        name = workflow.name
        text = workflow.read_bytes()
        # Any workflow, present or future, must not carry its own pin.
        if b'actions/setup-python' in text:
            print(f'.github/workflows/{name} must use ./.github/actions/setup, '
                  'not its own setup-python pin')
            ok = False
    for name in WORKFLOWS:
        path = ROOT / '.github' / 'workflows' / name
        if not path.exists():
            print(f'.github/workflows/{name} is missing')
            ok = False
            continue
        if not SETUP_STEP_RE.search(path.read_bytes()):
            print(f'.github/workflows/{name} is missing the shared setup step')
            ok = False
    return ok


def check_dialect_literals():
    """The definition table owns the dialect; call sites read its constant."""
    hits = []
    for path in _iter_files(('ai_router',)):
        rel = path.relative_to(ROOT)
        if rel.as_posix() == TABLE_OWNER:
            continue
        if DIALECT_LITERAL_RE.search(path.read_bytes()):
            hits.append(str(rel))
    if hits:
        print('dialect compared against a raw string; read the constant in '
              f'{TABLE_OWNER} instead (Plan 152)')
        for hit in hits:
            print(f'  {hit}')
        return False
    return True


def _model_value(node):
    if isinstance(node, ast.Name):
        return bool(MODEL_NAMES.search(node.id)) or node.id == 'bare'
    if isinstance(node, ast.Attribute):
        return bool(MODEL_NAMES.search(node.attr)) or node.attr == 'upstream_id'
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value in (
            'model', 'slug', 'vendor', 'upstream_id')
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == 'str' and node.args:
            return _model_value(node.args[0])
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'get' and node.args:
                return isinstance(node.args[0], ast.Constant) and node.args[0].value in (
                    'model', 'slug', 'vendor', 'upstream_id')
            if node.func.attr in ('lower', 'casefold', 'strip', 'removeprefix', 'removesuffix'):
                return _model_value(node.func.value)
    return False


def _name_literal(node):
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and bool(node.value)
    return isinstance(node, (ast.Tuple, ast.List, ast.Set)) and any(map(_name_literal, node.elts))


def check_model_decisions():
    """Model names belong to data and routing, never runtime behavior forks."""
    hits = []
    for path in _iter_files(('ai_router',)):
        if path.suffix != '.py':
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            hits.append(f'{rel}: invalid Python')
            continue
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                values = [node.left, *node.comparators]
                named = any((_model_value(a) and _name_literal(b)) or
                            (_name_literal(a) and _model_value(b))
                            for a, b in zip(values, values[1:]))
            else:
                named = (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                         and node.func.attr in ('startswith', 'endswith')
                         and _model_value(node.func.value) and any(map(_name_literal, node.args)))
            if not named:
                continue
            owner = parents.get(node)
            while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(owner)
            if (rel, getattr(owner, 'name', None), ast.unparse(node)) not in MODEL_ROUTING_EXCEPTIONS:
                hits.append(f'{rel}:{node.lineno}')
    if hits:
        print('model-name behavior decision; use captured capability data (Plan 188):')
        for hit in hits:
            print(f'  {hit}')
    return not hits


def main():
    # Every scan runs (no short-circuit) so one run reports all failures.
    results = (check_request_cap(), check_secrets(),
               check_publication_identifiers(), check_setup_single_owner(),
               check_dialect_literals(), check_model_decisions())
    ok = all(results)
    print(f'policy-scans: {"pass" if ok else "FAIL"}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
