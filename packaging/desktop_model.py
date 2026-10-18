"""One menu model for native shells and the Linux control-window fallback."""


def item(label, action=None, *, enabled=True, checked=False, children=None):
    return dict(label=label, action=action, enabled=enabled, checked=checked,
                children=children or [])


def _version(value):
    try:
        parts = tuple(map(int, value.split('.')))
        return parts + (0,) * (4 - len(parts))
    except (AttributeError, ValueError):
        return (0, 0, 0, 0)


def menu(facts, *, busy=None, available=None, checked_update=None):
    changing = not busy
    status = busy or facts.get('status', 'Status unknown')
    rows = [item('SCG Router — ' + status, enabled=False), item('')]
    update = facts.get('update', {})
    repair = update.get('required_action') == 'repair'
    checked = (checked_update if checked_update and all(checked_update.get(key) == value
        for key, value in (('installed', facts.get('version')), ('channel', update.get('channel')),
                          ('source', update.get('source')))) and update.get('source')
        and _version(checked_update.get('latest')) >= _version(update.get('latest_known_version'))
        and (checked_update.get('checked_at') or '') >= (update.get('last_successful_check_at') or '') else None)
    latest = update.get('latest_known_version', 'Unknown')
    if checked:
        latest = checked.get('latest') or latest
        available = latest
    available = available or (latest if update.get('required_action') == 'update' else None)
    available = available if _version(available) > _version(facts.get('version')) else None
    if repair:
        rows += [item('Updates need repair', enabled=False)]
    repairs = update.get('component_repairs', {})
    for component, label in (('assistants', 'Assistant connections need repair'),
                              ('controls', 'Router controls need repair')):
        if repairs.get(component) == 'failed' or component == 'controls' and repairs.get('controls_launchers') == 'failed':
            rows += [item(label, enabled=False)]
    if facts.get('menu_delivery') == 'failed':
        rows += [item('Menu update needs repair; choose Update or repair', enabled=False)]
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
            ('setup.status', 'Check setup…'), ('setup.resume', 'Update or repair…'),
            ('setup.add', 'Connect another assistant…'), ('setup.key', 'Replace model key…'),
            ('router.restart', 'Restart Router…'), ('setup.remove', 'Remove Router…'))]),
        item('Updates', children=[
            item('Running version ' + facts.get('running_version', 'Unknown'), enabled=False),
            item('Latest known ' + update.get('channel', 'stable') + ' version ' + latest, enabled=False),
            item('Last successful check ' + (checked['at'] if checked else update.get('last_successful_check', 'Unknown')), enabled=False),
            item('Repair now…', 'setup.resume', enabled=changing) if repair else
            item('Installed version ' + facts.get('version', 'Unknown'), enabled=False),
            item('Check for updates…', 'updates.check', enabled=changing),
            item('Install update ' + available + '…' if available else 'No update checked',
                 'updates.install', enabled=changing and bool(available) and not repair)]),
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
