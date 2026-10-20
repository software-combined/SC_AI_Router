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
        options += [item('Open ' + client['label'], client['id'] + '.open', enabled=changing)]
        selected = next((c['label'] for c in client['choices']
                         if c['id'] == client['selected']), 'Check setup')
        rows.append(item(client['label'] + ' — ' + selected, children=options))
    version, running = facts.get('version', 'Unknown'), facts.get('running_version', 'Unknown')
    updates = [item('Installed version ' + version, enabled=False)]
    if running != version:
        # An update the service has not started yet; a restart starts it.
        updates.append(item('Running version ' + running, enabled=False))
        if not repair and version != 'Unknown':
            updates.append(item('Restart Router to use version ' + version + '…', 'router.restart',
                                enabled=changing))
    if repair or latest != version:
        updates.append(item('Latest known ' + update.get('channel', 'stable') + ' version ' + latest,
                            enabled=False))
    updates += [
        item('Last successful check ' + (checked['at'] if checked else update.get('last_successful_check', 'Unknown')), enabled=False)]
    if repair:
        updates.append(item('Repair now…', 'setup.resume', enabled=changing))
    updates.append(item('Check for updates…', 'updates.check', enabled=changing))
    if available and not repair:
        updates.append(item('Install update ' + available + '…', 'updates.install', enabled=changing))
    rows += [item(''), item('Manage Router', children=[
        item(label, action, enabled=changing) for action, label in (
            ('setup.status', 'Check setup…'), ('setup.resume', 'Update or repair…'),
            ('setup.add', 'Connect another assistant…'), ('setup.key', 'Replace model key…'),
            ('router.restart', 'Restart Router…'), ('setup.remove', 'Remove Router…'))]),
        item('Updates', children=updates),
        item('Help', children=[item('Troubleshooting…', 'help.guide', enabled=changing),
                               item('Create support bundle…', 'help.support', enabled=changing)]),
        item(''), item('Start at sign-in', 'startup.toggle', enabled=changing,
                       checked=facts.get('autostart', False)),
        item('Quit SCG Router menu', 'menu.quit', enabled=changing)]
    return dict(schema=1, status=status, menu=rows)


def chooser(rows):
    """(details, actions) for the control window, which has no submenus.

    A connection's current choice is a detail, not an action: choosing it does nothing.
    An action offered twice keeps its first place and its later, more specific label.
    """
    details, options = [], {}
    for row in rows:
        children = row['children']
        client = bool(children) and (children[0]['action'] or '').startswith(('codex.', 'claude.'))
        if client:
            details.append(row['label'].replace(' — ', ': ', 1))
        for child in children or [row]:
            action, label = child['action'], child['label']
            if not action:
                if label and not client:
                    details.append(label)
            elif child['enabled'] and action != 'menu.quit' and not (client and child['checked']):
                if action == 'startup.toggle':
                    label = 'Turn %s start at sign-in' % ('off' if child['checked'] else 'on')
                elif client and not action.endswith('.open'):
                    label = '%s: switch to %s' % (row['label'].split(' — ')[0], label.rstrip('…'))
                options[action] = label
    return details, list(options.items())
