import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).parents[1] / 'src/ludus-launch-options.py'
SPEC = importlib.util.spec_from_file_location('launch_hud_tests', SOURCE)
L = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(L)
H = L.HUD


def config(hud=True, scb=False, games=None):
    return {'version': 1, 'global': {'mangohud': dict(H.DEFAULT, enabled=hud),
                                    'launch_options': dict(L.DEFAULT, scopebuddy=scb)},
            'games': games or {}}


def document(value=None):
    field = '' if value is None else '"LaunchOptions" ' + L.quote(value)
    return '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "42" { ' + field + ' } } } } } }'


class PolicyTests(unittest.TestCase):
    def test_strict_schema_and_inheritance(self):
        for value in ({'font_size': 17}, {'font_size': 65}, {'font_size': True}, {'font_size': '32'},
                      {'position': 'no'}, {'exec': 'touch /tmp/no'}, {'fps': 1},
                      {'toggle_hud': 'F12\nexec=id'}, {'toggle_hud': '$(id)'},
                      {'toggle_hud': 'Shift_R+Shift_R+F12'}):
            with self.subTest(value=value), self.assertRaises(ValueError): H.validate(value)
        c = config(games={'42': {'mangohud': {'mode': 'disabled'}}})
        self.assertIsNone(H.effective(c, '42'))
        self.assertIsNotNone(H.effective(c, '43'))
        c['global']['mangohud']['enabled'] = False
        c['games']['42']['mangohud']['mode'] = 'enabled'
        self.assertIsNotNone(H.effective(c, '42'))
        self.assertIsNone(H.effective(c, '43'))
        with self.assertRaises(ValueError): H.validate({'mode': 'enabled', 'font_size': 50}, game=True)
        L.sibling('ludus-proton-dpi').validate_config(c)
        c['global']['mangohud']['fps'] = 'yes'
        with self.assertRaises(ValueError): L.sibling('ludus-proton-dpi').validate_config(c)

    def test_feature_saves_and_resets_are_independent(self):
        c = config(games={'42': {'mangohud': {'mode': 'enabled'}, 'proton_overlay_dpi': 150}})
        launch = copy.deepcopy(c['global']['launch_options'])
        L.save_policy(c, {'scope': 'mangohud-reset'})
        self.assertEqual(c['global']['launch_options'], launch)
        self.assertEqual(c['games']['42'], {'proton_overlay_dpi': 150})
        L.save_policy(c, {'scope': 'mangohud-global', 'policy': {'enabled': True}})
        L.save_policy(c, {'scope': 'reset'})
        self.assertTrue(H.effective(c, '42'))
        L.save_policy(c, {'scope': 'game', 'appid': '42', 'policy': {'mode': 'disabled'}})
        self.assertTrue(L.enabled(L.effective(c, '42')))

    def test_config_has_only_supported_layout(self):
        text = H.render(H.DEFAULT)
        self.assertIn('font_size=32\n', text)
        self.assertIn('toggle_hud=Shift_R+F12\n', text)
        self.assertNotIn('enabled=', text)
        self.assertIn('fps=0\n', H.render({'fps': False}))

    def test_composition_and_unmanaged_conflicts(self):
        path = '/home/player with space/.config/ludus/mangohud/MangoHud.conf'
        p = L.effective(config(), '42')
        command = L.compose('PROTON_LOG=1 gamemoderun %command% -old', p, mangohud_path=path)
        self.assertIn("gamemoderun env MANGOHUD_CONFIGFILE='/home/player with space/", command)
        self.assertIn(' MANGOHUD=1 %command% -old', command)
        p = L.effective(config(scb=True), '42')
        command = L.compose(None, p, mangohud_path=path)
        self.assertEqual(command.count('scb '), 1)
        self.assertEqual(command.count('--mangoapp'), 1)
        self.assertNotIn('MANGOHUD=1', command)
        for old in ('gamescope -- %command%', 'scb -f -- %command%', 'mangohud %command%',
                    'MANGOHUD=1 %command%', 'env MANGOHUD_CONFIG=x %command%', 'echo hi; %command%'):
            with self.subTest(old=old), self.assertRaises(ValueError):
                L.compose(old, p, mangohud_path=path)


class PrivateConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.state = {}
        self.saved = []
        self.io = L.HUD_IO
        self.persist = lambda: self.saved.append(copy.deepcopy(self.state))

    def prepare(self, policy=None):
        return H.prepare(self.home, policy or H.DEFAULT, self.state, self.persist, self.io)

    def test_backup_once_private_modes_and_restore_leaves_original(self):
        original = self.home / '.config/MangoHud/MangoHud.conf'
        original.parent.mkdir(parents=True)
        original.write_text('font_size=21\n# user settings\n')
        before = original.read_bytes()
        path = Path(self.prepare())
        backup = Path(self.state['backup'])
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        first = path.stat().st_mtime_ns
        self.prepare()
        self.assertEqual(path.stat().st_mtime_ns, first)
        self.assertEqual(len(list(backup.parent.iterdir())), 1)
        H.cleanup(self.home, self.state, self.persist, self.io, referenced=False)
        self.assertFalse(path.exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertTrue(backup.exists())

    def test_configuration_journal_recovers_after_replace(self):
        atomic = self.io.atomic_text
        def interrupted(path, text):
            atomic(path, text)
            raise OSError('crash after replacement')
        with mock.patch.object(self.io, 'atomic_text', side_effect=interrupted):
            with self.assertRaises(OSError): self.prepare()
        self.assertIn('pending', self.state)
        self.prepare({'font_size': 40})
        self.assertIn('font_size=40', H.config_path(self.home).read_text())
        self.assertNotIn('pending', self.state)

    def test_config_drift_and_symlinks_are_preserved(self):
        path = Path(self.prepare())
        path.write_text('manual')
        self.prepare()
        self.assertEqual(Path(self.state['drift_backup']).read_text(), 'manual')
        self.assertIn('font_size=32', path.read_text())
        path.write_text('second manual change')
        H.cleanup(self.home, self.state, self.persist, self.io, False)
        self.assertEqual(Path(self.state['drift_backup']).read_text(), 'second manual change')
        self.assertFalse(path.exists())
        target = self.home / 'target'
        target.write_text('keep')
        path.symlink_to(target)
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(target.read_text(), 'keep')

    def test_symlinked_config_parent_is_not_followed(self):
        target = self.home / 'outside'
        target.mkdir()
        (self.home / '.config').symlink_to(target)
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(list(target.iterdir()), [])

    def test_symlinked_optional_user_config_does_not_block(self):
        user = self.home / '.config/MangoHud/MangoHud.conf'
        user.parent.mkdir(parents=True)
        target = self.home / 'dotfile'
        target.write_text('font_size=20')
        user.symlink_to(target)
        path = Path(self.prepare())
        self.assertTrue(path.exists())
        self.assertIn('skipped', self.state['backup_note'])
        self.assertEqual(target.read_text(), 'font_size=20')

    def test_later_user_config_and_reenable_are_backed_up(self):
        self.prepare()
        self.assertNotIn('backup_done', self.state)
        user = self.home / '.config/MangoHud/MangoHud.conf'
        user.parent.mkdir(parents=True)
        user.write_text('later config')
        self.prepare()
        self.assertEqual(Path(self.state['backup']).read_text(), 'later config')
        H.cleanup(self.home, self.state, self.persist, self.io, False)
        user.write_text('changed before reenable')
        self.prepare()
        self.assertEqual(Path(self.state['backup']).read_text(), 'changed before reenable')



class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        root = self.home / '.local/share/Steam'
        (root / 'config').mkdir(parents=True)
        (root / 'config/loginusers.vdf').write_text('"users" { "76561197960265851" {} }')
        self.vdf = root / 'userdata/123/config/localconfig.vdf'
        self.vdf.parent.mkdir(parents=True)
        self.vdf.write_text(document('-old'))
        (root / 'steamapps/common/Example').mkdir(parents=True)
        (root / 'steamapps/appmanifest_42.acf').write_text('"AppState" { "appid" "42" "name" "Example" "installdir" "Example" }')
        self.request = {'action': 'reconcile', 'config': config(), 'libraries': []}
        self.stopped = mock.patch.object(L, 'steam_stopped')
        self.stopped.start()
        self.addCleanup(self.stopped.stop)
        self.tools = mock.patch.object(L, 'scopebuddy_check', return_value=('scb', []))
        self.tools.start()
        self.addCleanup(self.tools.stop)

    def run_policy(self, c=None):
        if c is not None: self.request['config'] = c
        return L.worker(self.request, self.home)

    def current(self):
        return L.launch_value(L.apps_block(self.vdf.read_text()), '42')

    def test_login_idempotence_transitions_and_full_reset(self):
        first = self.run_policy()
        self.assertEqual(first['accounts']['123']['42']['mangohud_status'], 'mangohud')
        self.assertIn('MANGOHUD=1', self.current())
        original = self.vdf.read_bytes()
        self.run_policy()
        self.assertEqual(self.vdf.read_bytes(), original)
        result = self.run_policy(config(scb=True))
        self.assertEqual(result['accounts']['123']['42']['mangohud_status'], 'mangoapp')
        self.assertIn('--mangoapp', self.current())
        self.assertNotIn('MANGOHUD=1', self.current())
        self.run_policy(config(hud=False, scb=True))
        self.assertIn('scb -f --', self.current())
        self.assertNotIn('mango', self.current().lower())
        self.assertFalse(H.config_path(self.home).exists())
        self.run_policy(config(hud=False))
        self.assertEqual(self.current(), '-old')
        self.assertFalse(L.uninstall_blockers({'users': {'alice': self.run_policy()}}, ['alice']))

    def test_unmanaged_wrapper_blocks_only_that_game(self):
        self.vdf.write_text(document('gamescope -f -- %command%'))
        result = self.run_policy()
        self.assertEqual(result['accounts']['123']['42']['status'], 'conflict')
        self.assertEqual(self.current(), 'gamescope -f -- %command%')
        path = H.config_path(self.home)
        self.assertTrue(path.exists())
        mtime = path.stat().st_mtime_ns
        self.run_policy()
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(result['mangohud']['status'], 'applied')

    def test_config_failure_does_not_block_scopebuddy_or_steam(self):
        with mock.patch.object(H, 'prepare', side_effect=OSError('read-only config')):
            result = self.run_policy(config(scb=True))
        self.assertNotIn('error', result)
        record = result['accounts']['123']['42']
        self.assertEqual(record['status'], 'applied')
        self.assertEqual(record['mangohud_status'], 'error')
        self.assertIn('read-only', record['mangohud_error'])
        self.assertIn('scb -f --', self.current())
        self.assertNotIn('--mangoapp', self.current())

    def test_changed_steam_value_is_preserved_on_reset_with_config_retained(self):
        self.run_policy()
        self.vdf.write_text(document(self.current() + ' -manual'))
        result = self.run_policy(config(hud=False))
        self.assertEqual(result['accounts']['123']['42']['status'], 'conflict')
        self.assertTrue(self.current().endswith(' -manual'))
        self.assertTrue(H.config_path(self.home).exists())
        self.assertTrue(L.uninstall_blockers({'users': {'alice': result}}, ['alice']))

    def test_reset_removes_hud_from_owned_uninstalled_game(self):
        self.run_policy(config(scb=True))
        (self.home / '.local/share/Steam/steamapps/appmanifest_42.acf').unlink()
        self.run_policy(config(hud=False, scb=True))
        self.assertIn('scb -f --', self.current())
        self.assertNotIn('--mangoapp', self.current())
        self.assertFalse(H.config_path(self.home).exists())

    def test_bare_adopted_scopebuddy_can_add_and_remove_mangoapp(self):
        self.vdf.write_text(document('scb -- %command% -old'))
        self.run_policy(config(hud=False, scb=True))
        self.run_policy(config(scb=True))
        self.assertIn('--mangoapp', self.current())
        self.assertEqual(self.current().count('scb '), 1)
        self.run_policy(config(hud=False, scb=False))
        self.assertEqual(self.current(), 'scb -- %command% -old')

    def test_mangoapp_is_applied_without_a_probe(self):
        self.tools.stop()
        with mock.patch.object(L.shutil, 'which', side_effect=lambda name, path=None:
                               '/usr/bin/' + name if name in ('scb', 'gamescope', 'kscreen-doctor', 'jq') else None) as which:
            result = self.run_policy(config(scb=True))
        self.assertNotIn('mangoapp', [call.args[0] for call in which.call_args_list])
        self.assertIn('--mangoapp', self.current())
        self.assertEqual(result['accounts']['123']['42']['mangohud_status'], 'mangoapp')

    def action(self, scope):
        return L.worker({'action': scope, 'account': '123', 'appid': '42'}, self.home)

    def test_accept_reset_resume_restores_pre_ludus_baseline(self):
        for scoped in (False, True):
            with self.subTest(scoped=scoped):
                self.run_policy(config(scb=scoped))
                edited = self.current() + ' -foo'
                self.vdf.write_text(document(edited))
                self.run_policy()
                self.action('accept')
                self.run_policy(config(hud=False))
                self.action('resume')
                state = self.run_policy()
                self.assertEqual(self.current(), '-old')
                self.assertEqual(state['accounts']['123']['42']['hud_manual_backup'], edited)
                self.assertFalse(H.config_path(self.home).exists())
                self.assertFalse(L.uninstall_blockers({'users': {'alice': state}}, ['alice']))

    def test_replace_reset_restores_pre_ludus_baseline(self):
        self.run_policy()
        edited = self.current() + ' -foo'
        self.vdf.write_text(document(edited))
        self.run_policy()
        self.action('replace')
        self.run_policy()
        self.assertIn('MANGOHUD=1', self.current())
        state = self.run_policy(config(hud=False))
        self.assertEqual(self.current(), '-old')
        self.assertEqual(state['accounts']['123']['42']['hud_manual_backup'], edited)
        self.assertFalse(L.uninstall_blockers({'users': {'alice': state}}, ['alice']))

    def test_no_safe_baseline_keeps_recovery_actionable(self):
        self.run_policy()
        edited = self.current() + ' -foo'
        self.vdf.write_text(document(edited))
        self.run_policy()
        path = self.home / '.local/state/ludus/launch-options/state.json'
        state = L.json_read(path, {})
        state['accounts']['123']['42']['original'] = edited
        L.json_write(path, state)
        self.action('replace')
        state = self.run_policy(config(hud=False))
        self.assertEqual(state['accounts']['123']['42']['status'], 'conflict')
        self.assertEqual(self.current(), edited)

    def test_failed_initial_prepare_then_disable_clears_error(self):
        with mock.patch.object(H, 'prepare', side_effect=ValueError('symlink')):
            state = self.run_policy()
        self.assertIn('error', state['mangohud'])
        state = self.run_policy(config(hud=False))
        self.assertNotIn('error', state['mangohud'])
        self.assertEqual(state['mangohud']['status'], 'restored')

    def test_quoted_home_reference_keeps_config_on_conflict_and_accept(self):
        home = self.home / "o'brien"
        home.mkdir()
        for entry in list(self.home.iterdir()):
            if entry != home: entry.rename(home / entry.name)
        self.vdf = home / self.vdf.relative_to(self.home)
        self.home = home
        self.run_policy()
        self.assertNotIn(str(H.config_path(home)), self.current())
        edited = self.current() + ' -manual'
        self.vdf.write_text(document(edited))
        self.run_policy(config(hud=False))
        self.assertTrue(H.config_path(home).exists())
        self.action('accept')
        self.run_policy()
        self.assertTrue(H.config_path(home).exists())


    def test_layout_change_is_pending_then_applied(self):
        result = self.run_policy()
        changed = config()
        changed['global']['mangohud']['font_size'] = 40
        with mock.patch.object(L, 'players', return_value={'alice': None}), \
             mock.patch.object(L, 'run_worker', return_value=result):
            settings = L.public_settings(changed, [])
        self.assertEqual(settings['users']['alice']['accounts']['123']['42']['status'], 'pending-apply')
        self.run_policy(changed)
        self.assertIn('font_size=40', H.config_path(self.home).read_text())


if __name__ == '__main__': unittest.main()
