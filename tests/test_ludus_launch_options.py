import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

SOURCE = pathlib.Path(__file__).parents[1] / 'src/ludus-launch-options.py'
SPEC = importlib.util.spec_from_file_location('launch', SOURCE)
L = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(L)


def config(enabled=True, games=None):
    return {'version': 1, 'global': {'launch_options': dict(L.DEFAULT, profile='custom', scopebuddy=enabled)}, 'games': games or {}}


def document(options=None):
    field = '' if options is None else '"LaunchOptions" ' + L.quote(options)
    return '// preserved comment\r\n"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" {\r\n"42" { ' + field + ' "Other" "keep\\\\this" }\r\n} } } } "Unrelated" "unchanged" }\r\n'


class CompositionTests(unittest.TestCase):
    def test_preset_and_argument_positions(self):
        self.assertEqual(L.compose(None, dict(L.DEFAULT, profile='custom', scopebuddy=True)), 'scb -- %command%')
        self.assertEqual(L.compose('PROTON_LOG=1 gamemoderun %command% -old',
                                   dict(L.DEFAULT, profile='custom', scopebuddy=True, wrapper_args='-W 3840', game_args='-new')),
                         'PROTON_LOG=1 gamemoderun scb -W 3840 -- %command% -old -new')
        self.assertEqual(L.compose('-novid', dict(L.DEFAULT, profile='custom', scopebuddy=True)), 'scb -- %command% -novid')
        self.assertEqual(L.compose('scb -- %command%', dict(L.DEFAULT, profile='custom', scopebuddy=True)), 'scb -- %command%')

    def test_profiles(self):
        adaptive = dict(L.DEFAULT, scopebuddy=True)
        self.assertEqual(L.compose('-novid', adaptive),
                         'SCB_AUTO_RES=1 SCB_AUTO_HDR=1 SCB_AUTO_VRR=1 scb -f -- %command% -novid')
        upscale = dict(adaptive, profile='upscale-1080p', upscale_filter='fsr', sharpness=5)
        self.assertEqual(L.compose(None, upscale),
                         'SCB_AUTO_RES=1 SCB_AUTO_HDR=1 SCB_AUTO_VRR=1 scb -f -w 1920 -h 1080 -F fsr --sharpness 5 -- %command%')
        # A bare manual wrapper is replaced, never nested.
        self.assertEqual(L.compose('scb -- %command% -novid', dict(adaptive, profile='upscale-720p')),
                         'SCB_AUTO_RES=1 SCB_AUTO_HDR=1 SCB_AUTO_VRR=1 scb -f -w 1280 -h 720 -F nis -- %command% -novid')
        for bad in ({'profile': 'upscale-4k'}, {'upscale_filter': 'bicubic'}, {'sharpness': 21}, {'sharpness': '3'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError): L.validate_policy(bad)
        self.assertEqual(L.validate_policy({'mode': 'enabled', 'profile': 'default'}, game=True)['profile'], 'default')
        with self.assertRaises(ValueError): L.validate_policy({'profile': 'default'})

    def test_game_profile_overrides_global_profile(self):
        c = config()
        c['global']['launch_options'].update(profile='adaptive')
        c['games']['42'] = {'launch_options': {'mode': 'enabled', 'profile': 'upscale-1440p'}}
        self.assertEqual(L.effective(c, '42')['profile'], 'upscale-1440p')
        c['games']['42']['launch_options']['profile'] = 'default'
        self.assertEqual(L.effective(c, '42')['profile'], 'adaptive')
        # Policies saved before profiles keep their free-text arguments.
        legacy = {'version': 1, 'global': {'launch_options': {'scopebuddy': True, 'wrapper_args': '-W 3840'}}, 'games': {}}
        self.assertEqual(L.compose(None, L.effective(legacy, '42')), 'scb -W 3840 -- %command%')

    def test_unsafe_and_ambiguous_commands_are_rejected(self):
        for value in ('echo x; %command%', '"%command%"', '%command% %command%',
                      'scb -W 3840 -- %command%', 'scb -- scopebuddy -- %command%',
                      'gamescope -W 3840 -- %command%',
                      '$(touch /tmp/no) %command%', r'%command% -path foo\bar', 'scb'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                L.compose(value, dict(L.DEFAULT, profile='custom', scopebuddy=True))
        for value in ('$(id)', '-- %command%', '-x; id', '-x\n-y'):
            with self.assertRaises(ValueError): L.arguments(value)
        with self.assertRaises(ValueError): L.validate_policy({'wrapper_args': '--'})

    def test_game_inheritance_disable_and_arguments(self):
        c = config()
        c['global']['launch_options']['game_args'] = '-global'
        c['games']['42'] = {'launch_options': {'mode': 'enabled', 'game_args': '-local'}}
        self.assertEqual(L.compose(None, L.effective(c, '42')), 'scb -- %command% -global -local')
        c['games']['42']['launch_options']['mode'] = 'inherit'
        self.assertEqual(L.compose(None, L.effective(c, '42')), 'scb -- %command% -global')
        c['games']['42']['launch_options']['mode'] = 'disabled'
        self.assertFalse(L.enabled(L.effective(c, '42')))


class VdfTests(unittest.TestCase):
    def test_preserves_unrelated_bytes_and_escaped_values(self):
        before = document('say "hello" \\path')
        after = L.replace_launch(before, '42', 'scb -- %command%')
        self.assertEqual(after, before.replace(L.quote('say "hello" \\path'), L.quote('scb -- %command%')))
        self.assertEqual(L.launch_value(L.apps_block(before), '42'), 'say "hello" \\path')

    def test_absent_and_empty_are_distinct(self):
        self.assertIsNone(L.launch_value(L.apps_block(document()), '42'))
        self.assertEqual(L.launch_value(L.apps_block(document('')), '42'), '')
        after = L.replace_launch(document(), '99', 'scb -- %command%')
        self.assertEqual(L.launch_value(L.apps_block(after), '99'), 'scb -- %command%')
        after = L.replace_launch(after, '99', None)
        self.assertIsNone(L.launch_value(L.apps_block(after), '99'))

    def test_first_account_without_an_apps_section(self):
        before = '"UserLocalConfigStore" { "Unrelated" "preserved" }'
        self.assertIsNone(L.launch_value(L.apps_block(before), '42'))
        after = L.replace_launch(before, '42', 'scb -- %command%')
        self.assertEqual(L.launch_value(L.apps_block(after), '42'), 'scb -- %command%')
        self.assertIn('"Unrelated" "preserved"', after)
        self.assertEqual(L.replace_launch(before, '42', None), before)

    def test_malformed_or_duplicate_vdf_is_rejected(self):
        for value in ('"bad', '"x" {', '"x" "y" }', '"x" { "Key" "a" "key" "b" }',
                      '"x" { "k" "v" [$LINUX] }'):
            with self.subTest(value=value), self.assertRaises(ValueError): L.parse(value)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'localconfig.vdf'
        self.path.write_bytes(document('-old').encode())
        self.records = {}
        self.saved = []
        self.stopped = mock.patch.object(L, 'steam_stopped')
        self.stopped.start()
        self.addCleanup(self.stopped.stop)

    def run_policy(self, policy=None, installed=None, available=True):
        L.reconcile_file(self.path, self.records, policy or config(),
                         {'42'} if installed is None else installed,
                         lambda: self.saved.append(copy.deepcopy(self.records)),
                         ('scb', []) if available else (None, ['gamescope']))

    def current(self):
        return L.launch_value(L.apps_block(L.read_text(self.path)[0]), '42')

    def test_idempotence_and_restoration_preserve_later_unrelated_changes(self):
        self.run_policy()
        first = self.path.read_bytes()
        self.assertEqual(self.current(), 'scb -- %command% -old')
        self.assertEqual(self.saved[0]['42']['original'], '-old')
        self.assertIn('transaction', self.saved[0]['42'])
        self.run_policy()
        self.assertEqual(self.path.read_bytes(), first)
        self.path.write_bytes(first.replace(b'unchanged', b'edited later'))
        self.run_policy(config(False), installed=set())
        self.assertEqual(self.current(), '-old')
        self.assertIn(b'edited later', self.path.read_bytes())
        self.assertFalse(self.records['42']['managed'])

    def test_manual_edit_conflicts_even_on_reset(self):
        self.run_policy()
        self.path.write_text(document('manual %command%'))
        self.run_policy(config(False))
        self.assertEqual(self.current(), 'manual %command%')
        self.assertEqual(self.records['42']['status'], 'conflict')
        self.run_policy()
        self.assertEqual(self.current(), 'manual %command%')

    def test_absent_and_empty_restore(self):
        for original in (None, ''):
            with self.subTest(original=original):
                self.records = {}
                self.path.write_text(document(original))
                self.run_policy()
                self.run_policy(config(False))
                self.assertEqual(self.current(), original)

    def test_not_installed_and_missing_scb(self):
        self.run_policy(installed=set())
        self.assertEqual(self.records, {})
        self.run_policy(available=False)
        self.assertEqual(self.current(), '-old')
        self.assertEqual(self.records['42']['status'], 'unavailable')
        self.run_policy()
        self.run_policy(available=False)
        self.assertEqual(self.current(), '-old')
        self.assertFalse(self.records['42']['managed'])
        self.run_policy()
        self.assertEqual(self.current(), 'scb -- %command% -old')

    def test_missing_requirements_are_reported(self):
        self.run_policy(available=False)
        self.assertEqual(self.records['42']['error'], 'ScopeBuddy is unavailable; missing gamescope')

    def test_scopebuddy_check_requires_tools_and_accepts_long_name(self):
        present = {'scopebuddy', 'gamescope', 'kscreen-doctor', 'jq'}
        with mock.patch.object(L.shutil, 'which', side_effect=lambda name, path=None: name if name in present else None):
            self.assertEqual(L.scopebuddy_check(), ('scopebuddy', []))
            present.discard('jq')
            self.assertEqual(L.scopebuddy_check(), (None, ['jq']))
        self.assertEqual(L.compose('', dict(L.DEFAULT, profile='custom', scopebuddy=True), 'scopebuddy'), 'scopebuddy -- %command%')

    def test_interrupted_write_after_replace_is_recovered(self):
        atomic = L.atomic_text
        def interrupt(*args):
            atomic(*args)
            raise OSError('simulated crash after replacement')
        with mock.patch.object(L, 'atomic_text', side_effect=interrupt): self.run_policy()
        self.assertIn('transaction', self.records['42'])
        self.run_policy()
        self.assertEqual(self.current(), 'scb -- %command% -old')
        self.run_policy(config(False))
        self.assertEqual(self.current(), '-old')

    def test_interrupted_write_before_replace_and_manual_edit(self):
        with mock.patch.object(L, 'atomic_text', side_effect=OSError('write failed')): self.run_policy()
        self.path.write_text(document('manual'))
        self.run_policy()
        self.assertEqual(self.records['42']['status'], 'conflict')
        self.assertEqual(self.current(), 'manual')

    def test_ambiguous_existing_command_can_be_accepted(self):
        self.path.write_text(document('echo hi; %command%'))
        self.run_policy()
        self.assertEqual(self.records['42']['status'], 'conflict')
        self.assertEqual(self.current(), 'echo hi; %command%')

    def test_accepted_override_is_untouched_and_resume_takes_new_baseline(self):
        self.run_policy()
        self.path.write_text(document('manual %command%'))
        self.run_policy()
        directory = pathlib.Path(self.temp.name) / '.local/state/ludus/launch-options'
        directory.mkdir(parents=True)
        state_path = directory / 'state.json'
        L.json_write(state_path, {'version': 1, 'accounts': {'123': self.records}})
        with mock.patch.object(L.os, 'getuid', return_value=1000):
            result = L.worker({'action': 'accept', 'account': '123', 'appid': '42'}, self.temp.name)
            self.records = result['accounts']['123']
            self.run_policy()
            self.assertEqual(self.current(), 'manual %command%')
            self.assertEqual(self.records['42']['status'], 'manual-override')
            result = L.worker({'action': 'resume', 'account': '123', 'appid': '42'}, self.temp.name)
        self.records = result['accounts']['123']
        self.run_policy()
        self.assertEqual(self.current(), 'manual scb -- %command%')
        self.run_policy(config(False))
        self.assertEqual(self.current(), 'manual %command%')

    def replace_approved(self):
        directory = pathlib.Path(self.temp.name) / '.local/state/ludus/launch-options'
        directory.mkdir(parents=True, exist_ok=True)
        L.json_write(directory / 'state.json', {'version': 1, 'accounts': {'123': self.records}})
        with mock.patch.object(L.os, 'getuid', return_value=1000):
            self.records = L.worker({'action': 'replace', 'account': '123', 'appid': '42'}, self.temp.name)['accounts']['123']

    def test_replace_temporarily_owns_complex_value_and_restores_it(self):
        complex_value = 'gamescope -W 3840 -- %command% -old'
        self.path.write_text(document(complex_value))
        self.run_policy()
        self.assertEqual(self.records['42']['status'], 'conflict')
        self.replace_approved()
        self.assertEqual(self.records['42']['replace'], {'value': complex_value})
        self.run_policy()
        self.assertEqual(self.current(), 'scb -- %command%')
        self.run_policy()
        self.assertEqual(self.current(), 'scb -- %command%')
        self.run_policy(config(False))
        self.assertEqual(self.current(), complex_value)
        self.assertNotIn('replaced', self.records['42'])

    def test_replace_approval_lapses_when_value_changes_again(self):
        self.path.write_text(document('gamescope -- %command%'))
        self.run_policy()
        self.replace_approved()
        self.path.write_text(document('gamescope -f -- %command%'))
        self.run_policy()
        self.assertEqual(self.current(), 'gamescope -f -- %command%')
        self.assertEqual(self.records['42']['status'], 'conflict')
        self.assertNotIn('replace', self.records['42'])

    def test_different_players_keep_independent_restore_values(self):
        self.run_policy()
        first_records = self.records
        self.path.write_text(document('-second'))
        self.records = {}
        self.run_policy()
        self.run_policy(config(False))
        self.assertEqual(self.current(), '-second')
        self.assertEqual(first_records['42']['original'], '-old')

    def test_steam_running_prevents_write(self):
        with mock.patch.object(L, 'steam_stopped', side_effect=ValueError('Steam is running')):
            self.run_policy()
        self.assertEqual(self.current(), '-old')
        self.assertEqual(self.records['42']['status'], 'error')


class AccountTests(unittest.TestCase):
    def test_one_account_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / 'config').mkdir()
            (root / 'userdata/123/config').mkdir(parents=True)
            users = root / 'config/loginusers.vdf'
            users.write_text('"users" { "76561197960265851" {} }')
            self.assertEqual(L.steam_account(root)[0], '123')
            users.write_text('"users" { "76561197960265851" {} "76561197960265852" {} }')
            with self.assertRaisesRegex(ValueError, 'exactly one'): L.steam_account(root)
            users.write_text('"users" { "76561197960265851" {} }')
            (root / 'userdata/124').mkdir()
            with self.assertRaisesRegex(ValueError, 'Multiple'): L.steam_account(root)

    def test_schema_and_dpi_saves_preserve_launch_policy(self):
        dpi = L.sibling('ludus-proton-dpi')
        c = config(games={'42': {'launch_options': {'mode': 'disabled'}, 'proton_overlay_dpi': 150}})
        dpi.validate_config(c)
        with mock.patch.object(dpi, 'load_config', return_value=c), \
             mock.patch.object(dpi, 'read_json', return_value={'users': {}}), \
             mock.patch.object(dpi, 'atomic_json'), \
             mock.patch.object(dpi.grp, 'getgrnam'), \
             mock.patch.object(dpi, 'public_settings'):
            dpi.save_policy({'scope': 'game', 'appid': '42', 'policy': 'inherit'})
        self.assertEqual(c['games']['42'], {'launch_options': {'mode': 'disabled'}})


class WorkerIntegrationTests(unittest.TestCase):
    def test_full_worker_uses_only_installed_apps_and_restores_after_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp).resolve()
            steam = home / '.local/share/Steam'
            (steam / 'config').mkdir(parents=True)
            (steam / 'config/loginusers.vdf').write_text('"users" { "76561197960265851" {} }')
            vdf = steam / 'userdata/123/config/localconfig.vdf'
            vdf.parent.mkdir(parents=True)
            vdf.write_text(document())
            library = home / 'library'
            (library / 'steamapps/common/Example').mkdir(parents=True)
            manifest = library / 'steamapps/appmanifest_42.acf'
            manifest.write_text('"AppState" { "appid" "42" "name" "Example" "installdir" "Example" }')
            (library / 'steamapps/appmanifest_99.acf').write_text('"AppState" { "appid" "99" "installdir" "Missing" }')
            (library / 'steamapps/appmanifest_98.acf').write_text('broken')
            request = {'action': 'reconcile', 'config': config(), 'libraries': [str(library)]}
            with mock.patch.object(L, 'steam_stopped'), mock.patch.object(L.shutil, 'which', return_value='/usr/bin/scb'):
                result = L.worker(request, home)
                self.assertEqual(set(result['accounts']['123']), {'42'})
                self.assertEqual(L.launch_value(L.apps_block(vdf.read_text()), '42'), 'scb -- %command%')
                manifest.unlink()
                request['config'] = config(False)
                result = L.worker(request, home)
                self.assertEqual(result['accounts']['123']['42']['status'], 'restored')
                self.assertIsNone(L.launch_value(L.apps_block(vdf.read_text()), '42'))
            state = home / '.local/state/ludus/launch-options/state.json'
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            self.assertEqual(state.parent.stat().st_mode & 0o777, 0o700)

    def test_uninstall_blocks_owned_and_interrupted_values_but_not_accepted(self):
        settings = {'users': {'alice': {'accounts': {'123': {
            '42': {'managed': True}, '43': {'transaction': {'before': None}},
            '44': {'accepted': True, 'managed': False}}}},
            'bob': {'read_failed': True, 'error': 'Unreadable state', 'accounts': {}}}}
        blockers = L.uninstall_blockers(settings, ['alice', 'bob'])
        self.assertEqual({item.get('appid') for item in blockers}, {'42', '43', None})
        self.assertEqual(len(blockers), 3)

    def test_bad_state_is_rejected_without_losing_originals(self):
        for state in ({'version': 1, 'accounts': []},
                      {'version': 1, 'accounts': {'123': {'42': {'managed': True}}}},
                      {'version': 1, 'accounts': {'123': {'42': {'original': [], 'managed': False}}}}):
            with self.assertRaises(ValueError): L.validate_state(state)

    def test_coordinator_drops_all_player_credentials_and_isolates_python(self):
        from types import SimpleNamespace
        account = SimpleNamespace(pw_uid=1001, pw_gid=1002, pw_dir='/home/player')
        result = SimpleNamespace(returncode=0, stdout='{"version":1,"accounts":{}}', stderr='')
        with mock.patch.object(L.pwd, 'getpwnam', return_value=account), \
             mock.patch.object(L.os, 'getgrouplist', return_value=[1002, 1003]), \
             mock.patch.object(L.subprocess, 'run', return_value=result) as run:
            L.run_worker('player', {'action': 'status'})
        args, kwargs = run.call_args
        self.assertIn('-I', args[0])
        self.assertEqual(kwargs['user'], 1001)
        self.assertEqual(kwargs['group'], 1002)
        self.assertEqual(kwargs['extra_groups'], [1002, 1003])
        self.assertEqual(kwargs['cwd'], '/')
        self.assertEqual(kwargs['env']['HOME'], '/home/player')
        self.assertNotIn('shell', kwargs)

    def test_follow_default_and_disabled_clear_saved_game_arguments(self):
        for mode in ('inherit', 'disabled'):
            policy = config()
            L.save_policy(policy, {'scope': 'game', 'appid': '42', 'policy': {
                'mode': mode, 'wrapper_args': '-W 3840', 'game_args': '-novid'}})
            self.assertEqual(policy['games']['42']['launch_options'], {
                'mode': mode, 'wrapper_args': '', 'game_args': ''})

    def test_reset_preserves_dpi_and_global_enable_checks_scb(self):
        policy = config(games={'42': {'proton_overlay_dpi': 150, 'launch_options': {'mode': 'enabled'}}})
        policy['global']['proton_overlay_dpi'] = 200
        L.save_policy(policy, {'scope': 'reset'})
        self.assertEqual(policy['global'], {'proton_overlay_dpi': 200})
        self.assertEqual(policy['games']['42'], {'proton_overlay_dpi': 150})
        with mock.patch.object(L.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                L.save_policy(policy, {'scope': 'global', 'policy': {'scopebuddy': True}})


if __name__ == '__main__': unittest.main()
