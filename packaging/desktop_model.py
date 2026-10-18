"""One menu model for native shells and the Linux control-window fallback."""


def item(label, action=None, *, enabled=True, checked=False, children=None):
    return dict(label=label, action=action, enabled=enabled, checked=checked,
                children=children or [])


def menu(facts, *, busy=None, available=None):
    changing = not busy
    status = busy or facts.get('status', 'Status unknown')
    rows = [item('SCG Router — ' + status, enabled=False), item('')]
    if facts.get('menu_delivery') == 'failed':
        rows += [item('Menu update needs repair; choose Set up or repair', enabled=False)]
    for client in facts.get('clients', []):
        options = [item(choice['label'] + ('…' if choice['id'] != client['selected'] else ''),
                        client['id'] + '.' + choice['id'],
                        enabled=changing and choice.get('enabled', True),
                        checked=choice['id'] == client['selected'])
                   for choice in client['choices']]
        options += [item('Selected connection; replies are checked separately', enabled=False),
                    item('Open ' + client['label'], client['id'] + '.open', enabled=changing)]
        selected = next((c['label'] for c in client['choices']
                         if c['id'] == client['selected']), 'Check setup')
        rows.append(item(client['label'] + ' — ' + selected, children=options))
    rows += [item(''), item('Manage Router', children=[
        item(label, action, enabled=changing) for action, label in (
            ('setup.status', 'Check setup…'), ('setup.resume', 'Set up or repair…'),
            ('setup.add', 'Connect another assistant…'), ('setup.key', 'Replace model key…'),
            ('router.restart', 'Restart Router…'), ('setup.remove', 'Remove Router…'))]),
        item('Updates', children=[
            item('Installed version ' + facts.get('version', 'Unknown'), enabled=False),
            item('Check for updates…', 'updates.check', enabled=changing),
            item('Install update ' + available + '…' if available else 'No update checked',
                 'updates.install', enabled=changing and bool(available))]),
        item('Help', children=[item('Troubleshooting…', 'help.guide', enabled=changing),
                               item('Create support bundle…', 'help.support', enabled=changing)]),
        item(''), item('Start at sign-in', 'startup.toggle', enabled=changing,
                       checked=facts.get('autostart', False)),
        item('Quit SCG Router menu', 'menu.quit', enabled=changing)]
    return dict(schema=1, status=status, menu=rows)


def actions(rows, prefix=''):
    """Flatten a snapshot's enabled actions for a native chooser."""
    result = []
    for row in rows:
        if row.get('children'):
            result.extend(actions(row['children'], row['label'] + ': '))
        elif row.get('action') and row.get('enabled'):
            result.append((row['action'], prefix + ('✓ ' if row.get('checked') else '') + row['label']))
    return result
