#!/usr/bin/env python3
"""Console launch policy and unprivileged, reversible Steam KeyValues edits."""
import contextlib
import fcntl
import grp
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

CONFIG = '/etc/ludus/game-settings.json'
ROOT_STATE = '/var/lib/ludus/launch-options'
LOCK = '/etc/ludus/game-settings.lock'
MAX_BYTES = 16 * 1024 * 1024
WORKER_PATH = '/usr/local/bin:/usr/bin:/bin'
APPID = re.compile(r'[0-9]+\Z')
DEFAULT = {'scopebuddy': False, 'profile': 'adaptive', 'upscale_filter': 'nis',
           'sharpness': None, 'wrapper_args': '', 'game_args': ''}
GAME_FIELDS = {'mode', 'profile', 'upscale_filter', 'sharpness', 'wrapper_args', 'game_args'}
# Starting points rather than hand-written Gamescope settings. Every profile
# is expressed on the Steam command itself: ScopeBuddy reads SCB_* from the
# environment, and arguments given to scb are passed directly to Gamescope.
PROFILES = ('adaptive', 'upscale-720p', 'upscale-1080p', 'upscale-1440p', 'custom')
UPSCALE = {'upscale-720p': (1280, 720), 'upscale-1080p': (1920, 1080), 'upscale-1440p': (2560, 1440)}
AUTO_ENVIRONMENT = ['SCB_AUTO_RES=1', 'SCB_AUTO_HDR=1', 'SCB_AUTO_VRR=1']
# ScopeBuddy needs Gamescope, and its KDE automatic display detection needs
# kscreen-doctor and jq. Require all of them before writing an scb wrapper.
SCOPEBUDDY_TOOLS = ('gamescope', 'kscreen-doctor', 'jq')


def sibling(name):
    path = Path(__file__).with_name(name)
    if not path.exists(): path = path.with_suffix('.py')
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def arguments(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Arguments must be text of at most 2048 characters')
    # No shell syntax, interpolation, or additional command placeholders. Tokens
    # are re-quoted before storing in Steam; nothing is evaluated by this helper.
    if any(c in value for c in '\n\r\x00$`;&|<>()%'):
        raise ValueError('Use plain arguments, without shell operators or %command%')
    return shlex.split(value)


def validate_policy(policy, game=False):
    if not isinstance(policy, dict): raise ValueError('Invalid launch policy')
    allowed = GAME_FIELDS if game else set(DEFAULT)
    if set(policy) - allowed: raise ValueError('Unknown launch policy field')
    if game:
        if policy.get('mode', 'inherit') not in ('inherit', 'enabled', 'disabled'):
            raise ValueError('Invalid launch policy mode')
    elif type(policy.get('scopebuddy', False)) is not bool:
        raise ValueError('ScopeBuddy must be enabled or disabled')
    if policy.get('profile', 'default' if game else 'adaptive') not in PROFILES + (('default',) if game else ()):
        raise ValueError('Invalid ScopeBuddy profile')
    if policy.get('upscale_filter', 'nis') not in ('nis', 'fsr'):
        raise ValueError('Upscaling filter must be NIS or FSR')
    sharpness = policy.get('sharpness')
    if sharpness is not None and (type(sharpness) is not int or not 0 <= sharpness <= 20):
        raise ValueError('Sharpness must be a whole number from 0 to 20')
    for key in ('wrapper_args', 'game_args'):
        tokens = arguments(policy.get(key, ''))
        if key == 'wrapper_args' and '--' in tokens:
            raise ValueError('ScopeBuddy arguments must not contain the -- separator')
    return policy


def global_policy(config):
    saved = config['global'].get('launch_options', {})
    policy = dict(DEFAULT, **saved)
    # Policies saved before profiles existed used free-text arguments only.
    if 'profile' not in saved and policy['wrapper_args']: policy['profile'] = 'custom'
    return policy


def effective(config, appid):
    policy = global_policy(config)
    game = config['games'].get(appid, {}).get('launch_options', {})
    mode = game.get('mode', 'inherit')
    if mode == 'disabled': return dict(DEFAULT)
    if mode == 'inherit': return policy
    policy['scopebuddy'] = True
    if game.get('profile', 'default') != 'default':
        policy.update(profile=game['profile'], upscale_filter=game.get('upscale_filter', 'nis'),
                      sharpness=game.get('sharpness'), wrapper_args=game.get('wrapper_args', ''))
    policy['game_args'] = ' '.join(filter(None, (policy['game_args'], game.get('game_args', ''))))
    return policy


def scopebuddy_arguments(policy):
    """Return the environment assignments and Gamescope arguments of a profile."""
    if policy['profile'] == 'custom': return [], arguments(policy['wrapper_args'])
    gamescope = ['-f']
    if policy['profile'] in UPSCALE:
        width, height = UPSCALE[policy['profile']]
        gamescope += ['-w', str(width), '-h', str(height), '-F', policy['upscale_filter']]
        if policy['sharpness'] is not None: gamescope += ['--sharpness', str(policy['sharpness'])]
    return list(AUTO_ENVIRONMENT), gamescope


def scopebuddy_check():
    """Return the ScopeBuddy command name (or None) and any missing requirements."""
    wrapper = next((name for name in ('scb', 'scopebuddy') if shutil.which(name, path=WORKER_PATH)), None)
    missing = ([] if wrapper else ['scb or scopebuddy']) + [
        name for name in SCOPEBUDDY_TOOLS if not shutil.which(name, path=WORKER_PATH)]
    return (None if missing else wrapper), missing


def unavailable_message(missing):
    return 'ScopeBuddy is unavailable; missing ' + ', '.join(missing)


def enabled(policy):
    return policy['scopebuddy'] or bool(policy['game_args'].strip())


def compose(original, policy, wrapper_command='scb'):
    """Preserve simple existing wrappers verbatim; reject ambiguous shell grammar."""
    original = original or ''
    extra = shlex.join(arguments(policy['game_args']))
    if not enabled(policy): return original
    if '\\' in original or any(c in original for c in '\n\r\x00$`;&|<>()'):
        raise ValueError('Existing launch options use shell syntax; manual override required')
    tokens = shlex.split(original)
    if original.count('%command%') > 1 or ('%command%' in original and tokens.count('%command%') != 1):
        raise ValueError('Ambiguous %command% placement; manual override required')
    if '%command%' in original:
        # Only accept a standalone, unquoted placeholder so literal replacement
        # cannot change quoting or put the new wrapper inside another token.
        if not re.search(r'(?<!\S)%command%(?!\S)', original):
            raise ValueError('Quoted %command% is not supported')
        command = original
    else:
        if any(re.search(r'(^|/)(scb|scopebuddy)$', token) for token in tokens):
            raise ValueError('Existing wrapper has no %command%; manual override required')
        command = '%command%' + (' ' + original if original else '')
    wrappers = [t for t in tokens if re.search(r'(^|/)(scb|scopebuddy)$', t)]
    if policy['scopebuddy']:
        if any(re.search(r'(^|/)gamescope$', token) for token in tokens):
            raise ValueError('Existing Gamescope wrapper requires a manual override')
        environment, gamescope = scopebuddy_arguments(policy)
        wrapper = ' '.join(environment + [wrapper_command] + ([shlex.join(gamescope)] if gamescope else []) + ['--', '%command%'])
        if wrappers:
            # A bare "scb -- %command%" is swapped for the managed wrapper, so it
            # never runs twice; the exact original is still restored later.
            bare = re.fullmatch(r'(?:scb|scopebuddy)\s+--\s+%command%(\s+.*)?', original)
            if len(wrappers) != 1 or not bare:
                raise ValueError('Existing ScopeBuddy command requires a manual override')
            command = '%command%' + (bare.group(1) or '')
        command = command.replace('%command%', wrapper)
    return command + (' ' + extra if extra else '')


# A span-preserving parser: unrelated keys, comments and whitespace are never
# rendered again. Case-insensitive duplicate keys and unsupported syntax fail.
TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s"{}]+')


class Block:
    def __init__(self, end=0):
        self.entries = {}
        self.end = end


def unquote(raw):
    if not raw.startswith('"'): return raw
    return re.sub(r'\\([\\"])', r'\1', raw[1:-1])


def parse(text):
    tokens = []
    cursor = 0
    for match in TOKEN.finditer(text):
        if match.start() != cursor: raise ValueError('Malformed Steam KeyValues')
        cursor = match.end()
        raw = match.group()
        if raw.isspace() or raw.startswith('//'): continue
        if raw.startswith(('[', '#')): raise ValueError('Conditional KeyValues and directives are not supported')
        tokens.append((raw, match.start(), match.end()))
    if cursor != len(text): raise ValueError('Malformed Steam KeyValues')

    def block(index, nested=False, depth=0):
        if depth > 64: raise ValueError('Steam KeyValues nesting is too deep')
        result = Block(len(text))
        while index < len(tokens):
            raw, start, _end = tokens[index]
            if raw == '}':
                if not nested: raise ValueError('Unexpected closing brace')
                result.end = start
                return result, index + 1
            if raw == '{' or index + 1 >= len(tokens): raise ValueError('Missing KeyValues value')
            key = unquote(raw).lower()
            if key in result.entries: raise ValueError('Duplicate Steam KeyValues key')
            value, value_start, value_end = tokens[index + 1]
            if value == '{':
                value, index = block(index + 2, True, depth + 1)
                end = tokens[index - 1][2]
            elif value == '}': raise ValueError('Missing KeyValues value')
            else:
                value = unquote(value)
                index += 2
                end = value_end
            result.entries[key] = (value, start, end, value_start, value_end)
        if nested: raise ValueError('Unclosed Steam KeyValues block')
        return result, index
    return block(0)[0]


def child(block, name):
    entry = block.entries.get(name.lower())
    if not entry or not isinstance(entry[0], Block): raise ValueError('Missing Steam configuration section: ' + name)
    return entry[0]


APP_SECTIONS = ('Software', 'Valve', 'Steam', 'apps')


def apps_block(text):
    block = child(parse(text), 'UserLocalConfigStore')
    for name in APP_SECTIONS:
        if name.lower() not in block.entries: return Block()
        block = child(block, name)
    return block


def ensure_apps(text):
    """A first-time player can have installed shared games but no apps section."""
    block = child(parse(text), 'UserLocalConfigStore')
    for index, name in enumerate(APP_SECTIONS):
        if name.lower() not in block.entries:
            newline = '\r\n' if '\r\n' in text else '\n'
            insert = ''
            for part in reversed(APP_SECTIONS[index:]):
                insert = quote(part) + ' { ' + insert + ' }'
            return text[:block.end] + newline + insert + newline + text[block.end:]
        block = child(block, name)
    return text


def launch_value(apps, appid):
    entry = apps.entries.get(appid)
    if entry is None: return None
    if not isinstance(entry[0], Block): raise ValueError('Invalid Steam app section')
    launch = entry[0].entries.get('launchoptions')
    if launch is None: return None
    if not isinstance(launch[0], str): raise ValueError('Invalid LaunchOptions value')
    return launch[0]


def quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def replace_launch(text, appid, value):
    if value is not None: text = ensure_apps(text)
    apps = apps_block(text)
    entry = apps.entries.get(appid)
    newline = '\r\n' if '\r\n' in text else '\n'
    if entry is None:
        if value is None: return text
        insert = f'{newline}\t\t\t\t\t"{appid}" {{ "LaunchOptions" {quote(value)} }}{newline}'
        return text[:apps.end] + insert + text[apps.end:]
    block = child(apps, appid)
    launch = block.entries.get('launchoptions')
    if launch:
        launch_value(apps, appid)  # validate scalar before modifying any bytes
        _, start, end, vstart, vend = launch
        return text[:start] + text[end:] if value is None else text[:vstart] + quote(value) + text[vend:]
    if value is None: return text
    insert = f'{newline}\t\t\t\t\t\t"LaunchOptions"\t\t{quote(value)}{newline}'
    return text[:block.end] + insert + text[block.end:]


def read_text(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode): raise ValueError('Expected a regular file')
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES: raise ValueError('Steam configuration is too large')
    return data.decode('utf-8'), stat.S_IMODE(metadata.st_mode)


def atomic_text(path, text, mode=0o600):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.ludus-launch-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as target:
            try:
                previous = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(previous.st_mode):
                    os.fchown(target.fileno(), -1, previous.st_gid)
                    for attribute in os.listxattr(path, follow_symlinks=False):
                        os.setxattr(target.fileno(), attribute,
                                    os.getxattr(path, attribute, follow_symlinks=False))
            except FileNotFoundError: pass
            os.fchmod(target.fileno(), mode)
            target.write(text); target.flush(); os.fsync(target.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def json_read(path, default):
    try: return json.loads(read_text(path)[0])
    except FileNotFoundError: return default


def json_write(path, value):
    atomic_text(path, json.dumps(value, separators=(',', ':')) + '\n')


@contextlib.contextmanager
def locked(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally: os.close(fd)


def steam_stopped():
    result = subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', 'steam|steamwebhelper'],
                            stdout=subprocess.DEVNULL, check=False)
    if result.returncode != 1: raise ValueError('Close Steam before reconciling launch options')


def steam_account(root):
    users = child(parse(read_text(root / 'config/loginusers.vdf')[0]), 'users')
    ids = list(users.entries)
    if len(ids) != 1 or not APPID.fullmatch(ids[0]):
        raise ValueError('Expected exactly one Steam account; launch options skipped')
    steam_id = int(ids[0])
    if not 76561197960265728 < steam_id < 76561202255233024:
        raise ValueError('Invalid individual Steam account ID')
    account = str(steam_id & 0xffffffff)
    userdata = root / 'userdata'
    others = [p.name for p in userdata.iterdir() if p.name.isdecimal() and p.name not in (account, '0')]
    if others: raise ValueError('Multiple Steam account directories found; launch options skipped')
    path = userdata / account / 'config/localconfig.vdf'
    if path.resolve() != path:
        raise ValueError('Refusing a symlink inside Steam account configuration')
    return account, path


def installed_apps(libraries):
    result = set()
    for library in libraries:
        try: manifests = list((Path(library) / 'steamapps').glob('appmanifest_*.acf'))
        except OSError: continue
        for path in manifests:
            match = re.fullmatch(r'appmanifest_([0-9]+)\.acf', path.name)
            if not match: continue
            try:
                app = child(parse(read_text(path)[0]), 'AppState')
                if app.entries['appid'][0] != match[1]: continue
                directory = app.entries['installdir'][0]
                if not isinstance(directory, str) or '/' in directory or directory in ('', '.', '..'): continue
                if not (path.parent / 'common' / directory).is_dir(): continue
                name = app.entries.get('name', ('',))[0]
                if isinstance(name, str) and name.startswith(('Proton', 'Steam Linux Runtime')): continue
                result.add(match[1])
            except (OSError, ValueError, KeyError): continue
    return result


def reconcile_file(path, records, policy, installed, persist, scopebuddy):
    """Journal each planned value before replacing VDF; recover interrupted writes."""
    text, mode = read_text(path)
    if os.stat(path, follow_symlinks=False).st_uid != os.getuid():
        raise ValueError('Steam configuration must belong to this player')
    apps = apps_block(text)
    wrapper_command, missing = scopebuddy
    available = wrapper_command is not None
    for appid in sorted(installed | set(records), key=int):
        record = records.setdefault(appid, {})
        record['updated'] = int(time.time())
        record.pop('error', None)
        if record.get('accepted'):
            record['status'] = 'manual-override'
            continue
        try:
            current = launch_value(apps, appid)
            transaction = record.get('transaction')
            if transaction:
                if current == transaction['after']:
                    record.update(last=current, managed=transaction['managed'])
                    if not transaction['managed']:
                        record.pop('original', None); record.pop('replaced', None)
                elif current != transaction['before']:
                    record.update(status='conflict', current=current)
                    continue
                record.pop('transaction', None)
            target = effective(policy, appid)
            if record.pop('resume', False):
                record.pop('original', None)
                record['managed'] = False
            approved = record.pop('replace', None)
            if approved is not None:
                # Approval covers only the exact value the administrator saw.
                if current != approved['value']:
                    record.update(status='conflict', current=current,
                                  error='Launch options changed again after replacement was approved')
                    continue
                # Keep that value to restore, and build the managed command
                # without it for as long as Ludus owns this game.
                record.update(original=current, last=current, managed=True, replaced=True)
            if record.get('managed') and current != record.get('last'):
                record.update(status='conflict', current=current)
                continue
            if not enabled(target):
                if not record.get('managed'):
                    record['status'] = 'disabled'
                    continue
                desired, managed = record['original'], False
            else:
                if appid not in installed:
                    record['status'] = 'not-installed'
                    continue
                if target['scopebuddy'] and not available:
                    record.update(status='unavailable', error=unavailable_message(missing))
                    if not record.get('managed'): continue
                    # Remove only our unchanged value, avoiding a broken wrapper
                    # after ScopeBuddy disappears. Retry the saved policy later.
                    desired, managed = record['original'], False
                else:
                    original = '' if record.get('replaced') else (record['original'] if record.get('managed') else current)
                    try: desired, managed = compose(original, target, wrapper_command or 'scb'), True
                    except ValueError as error:
                        record.update(status='conflict', current=current, error=str(error))
                        continue
                    if 'original' not in record: record['original'] = current
            record['preview'] = desired
            if desired != current:
                updated = replace_launch(text, appid, desired)
                # Validate all resulting KeyValues before preparing the journal.
                apps_block(updated)
                record['transaction'] = {'before': current, 'after': desired, 'managed': managed}
                persist()
                steam_stopped()
                if read_text(path)[0] != text: raise ValueError('Steam configuration changed during reconciliation')
                atomic_text(path, updated, mode)
                text, apps = updated, apps_block(updated)
            record.update(last=desired, managed=managed, applied_policy=target,
                          status='unavailable' if target['scopebuddy'] and not available else ('applied' if managed else 'restored'))
            record.pop('transaction', None)
            record.pop('current', None)
            if not managed:
                record.pop('original', None); record.pop('replaced', None)
            persist()
        except (OSError, ValueError) as error:
            record.update(status='error', error=str(error))
    persist()


def validate_state(state):
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('accounts'), dict):
        raise ValueError('Invalid launch-options recovery state')
    for account, records in state['accounts'].items():
        if not APPID.fullmatch(account) or not isinstance(records, dict):
            raise ValueError('Invalid Steam account recovery state')
        for appid, record in records.items():
            if not APPID.fullmatch(appid) or not isinstance(record, dict):
                raise ValueError('Invalid game recovery state')
            for field in ('managed', 'accepted', 'resume', 'replaced'):
                if field in record and type(record[field]) is not bool:
                    raise ValueError('Invalid recovery flag')
            for field in ('original', 'last', 'current', 'preview'):
                if record.get(field) is not None and not isinstance(record[field], str):
                    raise ValueError('Invalid recorded launch value')
            if record.get('managed') and ('original' not in record or 'last' not in record):
                raise ValueError('Managed launch value is missing recovery data')
            replace = record.get('replace')
            if replace is not None and (not isinstance(replace, dict) or set(replace) != {'value'} or (
                    replace['value'] is not None and not isinstance(replace['value'], str))):
                raise ValueError('Invalid launch replacement approval')
            transaction = record.get('transaction')
            if transaction is not None:
                if not isinstance(transaction, dict) or set(transaction) != {'before', 'after', 'managed'}:
                    raise ValueError('Invalid pending launch write')
                if type(transaction['managed']) is not bool or any(
                        transaction[field] is not None and not isinstance(transaction[field], str)
                        for field in ('before', 'after')) or 'original' not in record:
                    raise ValueError('Invalid pending launch write values')
    return state


def worker(request, home=None):
    if os.getuid() == 0: raise ValueError('Steam worker must not run as root')
    home = Path(home or pwd.getpwuid(os.getuid()).pw_dir)
    directory = home / '.local/state/ludus/launch-options'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink(): raise ValueError('Launch recovery directory must not be a symlink')
    directory.chmod(0o700)
    path = directory / 'state.json'
    with locked(directory / 'state.lock'):
        state = validate_state(json_read(path, {'version': 1, 'accounts': {}}))
        action = request['action']
        if action in ('accept', 'resume', 'replace'):
            account, appid = request.get('account'), request.get('appid')
            record = state['accounts'].get(account, {}).get(appid)
            if not record: raise ValueError('No reconciliation record for this game')
            if action == 'accept':
                if record.get('status') != 'conflict':
                    raise ValueError('No manual override to accept')
                record.update(accepted=True, managed=False, status='manual-override')
                record.pop('transaction', None); record.pop('replace', None)
            elif action == 'replace':
                if record.get('status') != 'conflict' or 'current' not in record:
                    raise ValueError('No conflicting launch options to replace')
                record.update(replace={'value': record['current']}, status='pending-apply')
                record.pop('transaction', None)
            else:
                if not record.get('accepted'): raise ValueError('No accepted override to resume')
                record.update(accepted=False, resume=True, status='pending-apply')
            json_write(path, state)
        elif action == 'reconcile':
            try:
                steam_stopped()
                root = (home / '.local/share/Steam').resolve()
                account, vdf = steam_account(root)
                records = state['accounts'].setdefault(account, {})
                installed = installed_apps(request['libraries'] + [str(root)])
                reconcile_file(vdf, records, request['config'], installed,
                               lambda: json_write(path, state), scopebuddy_check())
                state.pop('error', None)
            except (OSError, ValueError) as error:
                state['error'] = str(error)
            json_write(path, state)
        elif action != 'status': raise ValueError('Invalid worker action')
        return state


def players():
    group = grp.getgrnam('ludus')
    return {p.pw_name: p for p in pwd.getpwall()
            if p.pw_uid != 0 and (p.pw_name in group.gr_mem or p.pw_gid == group.gr_gid)}


def run_worker(user, request):
    account = pwd.getpwnam(user)
    if account.pw_uid == 0: raise ValueError('Root cannot be a Ludus player')
    result = subprocess.run(
        [sys.executable, '-I', str(Path(__file__).resolve()), 'worker'],
        input=json.dumps(request), text=True, capture_output=True, timeout=90,
        user=account.pw_uid, group=account.pw_gid,
        extra_groups=os.getgrouplist(user, account.pw_gid), cwd='/',
        env={'HOME': account.pw_dir, 'USER': user, 'LOGNAME': user,
             'PATH': WORKER_PATH})
    if result.returncode: raise ValueError('Player launch-options helper failed: ' + result.stderr[-1000:])
    return json.loads(result.stdout)


def public_settings(config, known):
    _wrapper, missing = scopebuddy_check()
    users = {}
    for user in sorted(set(players()) | set(known)):
        try:
            state = run_worker(user, {'action': 'status'})
            for records in state['accounts'].values():
                for appid, record in records.items():
                    if record.get('managed') and not enabled(effective(config, appid)) and record.get('status') != 'conflict':
                        record['status'] = 'pending-restore'
                    elif record.get('managed') and record.get('applied_policy') != effective(config, appid) and record.get('status') != 'conflict':
                        record['status'] = 'pending-apply'
            users[user] = state
        except (KeyError, ValueError, subprocess.SubprocessError) as error:
            users[user] = {'accounts': {}, 'error': str(error), 'read_failed': True}
    return {'global': dict(DEFAULT, **config['global'].get('launch_options', {})),
            'games': {appid: item.get('launch_options', {}) for appid, item in config['games'].items()},
            'users': users, 'available': not missing, 'missing': missing}


def save_policy(config, argument):
    scope = argument.get('scope')
    if scope == 'reset':
        config['global'].pop('launch_options', None)
        for item in config['games'].values(): item.pop('launch_options', None)
    elif scope in ('global', 'game'):
        policy = dict(validate_policy(argument.get('policy'), scope == 'game'))
        if scope == 'game' and policy.get('mode', 'inherit') != 'enabled':
            # Only an explicit per-game override keeps its own settings.
            policy = {'mode': policy.get('mode', 'inherit'), 'wrapper_args': '', 'game_args': ''}
        if scope == 'global': config['global']['launch_options'] = policy
        else:
            appid = argument.get('appid')
            if not isinstance(appid, str) or not APPID.fullmatch(appid): raise ValueError('Invalid app ID')
            config['games'].setdefault(appid, {})['launch_options'] = policy
        if (scope == 'global' and policy.get('scopebuddy') or scope == 'game' and policy.get('mode') == 'enabled'):
            _wrapper, missing = scopebuddy_check()
            if missing: raise ValueError(unavailable_message(missing) + '; install it before enabling this preset')
    else: raise ValueError('Invalid launch-options scope')
    return config


def uninstall_blockers(settings, known):
    blockers = []
    for user, state in settings['users'].items():
        if state.get('read_failed') and user in known:
            blockers.append({'user': user, 'error': state['error']})
        for account, records in state['accounts'].items():
            for appid, record in records.items():
                if record.get('managed') or record.get('transaction'):
                    blockers.append({'user': user, 'account': account, 'appid': appid})
    return blockers


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action == 'worker':
        print(json.dumps(worker(json.load(sys.stdin)))); return
    if os.geteuid() != 0: raise ValueError('Management helper requires root')
    dpi = sibling('ludus-proton-dpi')
    Path(ROOT_STATE).mkdir(mode=0o700, parents=True, exist_ok=True)
    with locked(LOCK):
        config = dpi.load_config(CONFIG)
        known_path = Path(ROOT_STATE) / 'users.json'
        known = json_read(known_path, [])
        if action == 'reconcile':
            user = sys.argv[2]
            if user not in players(): raise ValueError('Not an enrolled Ludus player')
            if Path('/run/ludus-mount/active-user').read_text().strip() != user:
                raise ValueError('Not the active Ludus player')
            if user not in known:
                known.append(user); json_write(known_path, known)
            run_worker(user, {'action': 'reconcile', 'config': config, 'libraries': dpi.load_libraries()})
            return
        if action == 'save':
            argument = json.load(sys.stdin)
            if not isinstance(argument, dict): raise ValueError('Invalid launch-options request')
            if argument.get('scope') in ('accept', 'resume', 'replace'):
                user = argument.get('user')
                if user not in set(players()) | set(known): raise ValueError('Unknown Ludus player')
                run_worker(user, dict(argument, action=argument['scope']))
            else:
                save_policy(config, argument)
                dpi.validate_config(config)
                dpi.atomic_json(CONFIG, config, 0o640, grp.getgrnam('ludus-web').gr_gid)
        elif action not in ('settings', 'uninstall-check'):
            raise ValueError('usage: ludus-launch-options settings | save | reconcile USER | uninstall-check')
        settings = public_settings(config, known)
        if action == 'uninstall-check':
            blockers = uninstall_blockers(settings, known)
            print(json.dumps(blockers)); raise SystemExit(2 if blockers else 0)
        print(json.dumps(settings))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr); raise SystemExit(1)
