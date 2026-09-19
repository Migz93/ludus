import importlib.util
import json
import os
import pathlib
import stat
import tempfile
import unittest
from unittest import mock


SOURCE = pathlib.Path(__file__).parents[1] / "src" / "ludus-proton-dpi.py"
SPEC = importlib.util.spec_from_file_location("ludus_proton_dpi", SOURCE)
DPI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DPI)

HEADER = "WINE REGISTRY Version 2\n\n"
DESKTOP = "[Control Panel\\\\Desktop] 123\n"


class RegistryTests(unittest.TestCase):
    def test_parses_only_exact_section(self):
        text = (HEADER + '[Control Panel\\\\Desktop WindowMetrics]\n'
                '"LogPixels"=dword:00000078\n\n' + DESKTOP +
                '"LogPixels"=dword:00000060\n')
        _lines, value = DPI.parse_logpixels(text)
        self.assertEqual(value[1], "00000060")

    def test_updates_existing_value_and_preserves_other_content(self):
        text = HEADER + DESKTOP + '"Other"="keep"\n"LogPixels"=dword:00000060\n'
        changed, written = DPI.update_logpixels(text, "000000c0")
        self.assertTrue(written)
        self.assertIn('"Other"="keep"', changed)
        self.assertIn('"LogPixels"=dword:000000c0', changed)

    def test_inserts_in_exact_section(self):
        text = HEADER + DESKTOP + '"Other"="keep"\n\n[Environment]\n'
        changed, written = DPI.update_logpixels(text, "00000090")
        self.assertTrue(written)
        self.assertLess(changed.index('"LogPixels"'), changed.index("[Environment]"))

    def test_restores_present_original(self):
        changed, written = DPI.update_logpixels(HEADER + DESKTOP + '"LogPixels"=dword:000000c0\n',
                                                "00000078")
        self.assertTrue(written)
        self.assertIn("00000078", changed)

    def test_restores_absent_original(self):
        changed, written = DPI.update_logpixels(HEADER + DESKTOP + '"LogPixels"=dword:000000c0\n',
                                                None)
        self.assertTrue(written)
        self.assertNotIn("LogPixels", changed)

    def test_idempotent_when_correct(self):
        text = HEADER + DESKTOP + '"LogPixels"=dword:000000c0\n'
        self.assertEqual(DPI.update_logpixels(text, "000000c0"), (text, False))

    def test_rejects_duplicate_values(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            DPI.parse_logpixels(HEADER + DESKTOP + '"LogPixels"=dword:00000060\n' * 2)


class ValidationTests(unittest.TestCase):
    def prefix(self, root, appid="10"):
        library = pathlib.Path(root) / "library"
        pfx = library / "steamapps" / "compatdata" / appid / "pfx"
        pfx.mkdir(parents=True)
        reg = pfx / "user.reg"
        reg.write_text(HEADER + DESKTOP, encoding="utf-8")
        return library, reg

    def test_rejects_non_numeric_appid(self):
        with self.assertRaisesRegex(ValueError, "digits"):
            DPI.safe_user_reg("/tmp", "../10")

    def test_rejects_user_reg_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            library, reg = self.prefix(root)
            target = pathlib.Path(root) / "outside"
            target.write_text(HEADER, encoding="utf-8")
            reg.unlink(); reg.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                DPI.safe_user_reg(str(library), "10")

    def test_rejects_non_regular_file(self):
        with tempfile.TemporaryDirectory() as root:
            library, reg = self.prefix(root)
            reg.unlink(); reg.mkdir()
            with self.assertRaisesRegex(ValueError, "regular"):
                DPI.safe_user_reg(str(library), "10")

    def test_missing_prefix_returns_none(self):
        with tempfile.TemporaryDirectory() as root:
            library = pathlib.Path(root) / "library"
            (library / "steamapps" / "compatdata").mkdir(parents=True)
            self.assertIsNone(DPI.safe_user_reg(str(library), "10"))

    def test_missing_prefix_is_reported_without_creation(self):
        with tempfile.TemporaryDirectory() as root:
            library = pathlib.Path(root) / "library"
            (library / "steamapps" / "compatdata").mkdir(parents=True)
            record = {}
            DPI.reconcile_one("alice", "10", str(library), 200, record,
                              str(pathlib.Path(root) / "backups"))
            self.assertEqual(record["status"], "no-prefix")
            self.assertFalse((library / "steamapps" / "compatdata" / "10").exists())


class PolicyTests(unittest.TestCase):
    def test_inheritance_and_override_precedence(self):
        config = DPI.default_config()
        config["global"]["proton_overlay_dpi"] = 200
        self.assertEqual(DPI.effective_dpi(config, "10"), 200)
        config["games"]["10"] = {"proton_overlay_dpi": "disabled"}
        self.assertIsNone(DPI.effective_dpi(config, "10"))
        config["games"]["10"] = {"proton_overlay_dpi": 125}
        self.assertEqual(DPI.effective_dpi(config, "10"), 125)

    def test_rejects_invalid_schema_values(self):
        config = DPI.default_config()
        config["global"]["proton_overlay_dpi"] = 110
        with self.assertRaisesRegex(ValueError, "invalid global"):
            DPI.validate_config(config)

    def test_disabling_queues_each_managed_user_restore(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = pathlib.Path(root) / "game-settings.json"
            state_path = pathlib.Path(root) / "state.json"
            config = DPI.default_config()
            config["global"]["proton_overlay_dpi"] = 200
            config_path.write_text(json.dumps(config), encoding="utf-8")
            state = {"version": 1, "users": {
                "alice": {"10": {"managed": True, "status": "applied"}},
                "bob": {"10": {"managed": True, "status": "current"}}}}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with mock.patch.object(DPI.grp, "getgrnam",
                                   return_value=type("Group", (), {"gr_gid": os.getgid()})()), \
                    mock.patch.object(DPI.os, "chown"):
                DPI.save_policy({"scope": "global", "dpi": None},
                                str(config_path), str(state_path))
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["users"]["alice"]["10"]["pending_restore"])
            self.assertTrue(saved["users"]["bob"]["10"]["pending_restore"])
            self.assertEqual(saved["users"]["alice"]["10"]["status"], "pending-restore")

    def test_reenabling_cancels_queued_restore(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = pathlib.Path(root) / "game-settings.json"
            state_path = pathlib.Path(root) / "state.json"
            config_path.write_text(json.dumps(DPI.default_config()), encoding="utf-8")
            state_path.write_text(json.dumps({"version": 1, "users": {
                "alice": {"10": {"managed": True, "pending_restore": True,
                                 "status": "pending-restore"}}}}), encoding="utf-8")
            group = type("Group", (), {"gr_gid": os.getgid()})()
            with mock.patch.object(DPI.grp, "getgrnam", return_value=group), \
                    mock.patch.object(DPI.os, "chown"):
                DPI.save_policy({"scope": "global", "dpi": 150},
                                str(config_path), str(state_path))
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertFalse(saved["users"]["alice"]["10"]["pending_restore"])
            self.assertEqual(saved["users"]["alice"]["10"]["status"], "pending-apply")


class ReconcileOneTests(unittest.TestCase):
    def test_backup_restore_and_idempotency(self):
        with tempfile.TemporaryDirectory() as root:
            library = pathlib.Path(root) / "library"
            pfx = library / "steamapps" / "compatdata" / "10" / "pfx"
            pfx.mkdir(parents=True)
            reg = pfx / "user.reg"
            original = HEADER + DESKTOP + '"Other"="keep"\n'
            reg.write_text(original, encoding="utf-8")
            os.chmod(reg, 0o640)
            record = {}
            backup = pathlib.Path(root) / "backups"
            DPI.reconcile_one("alice", "10", str(library), 200, record, str(backup))
            first_mtime = reg.stat().st_mtime_ns
            self.assertEqual(record["status"], "applied")
            self.assertFalse(record["original_present"])
            self.assertEqual(stat.S_IMODE(reg.stat().st_mode), 0o640)
            backup_file = backup / "alice" / "10" / DPI.library_identity(str(library)) / "user.reg"
            self.assertEqual(backup_file.read_text(), original)
            DPI.reconcile_one("alice", "10", str(library), 200, record, str(backup))
            self.assertEqual(record["status"], "current")
            self.assertEqual(reg.stat().st_mtime_ns, first_mtime)
            reg.write_text(reg.read_text() + '"Later"="preserve"\n', encoding="utf-8")
            record["pending_restore"] = True
            DPI.reconcile_one("alice", "10", str(library), None, record, str(backup))
            restored = reg.read_text(encoding="utf-8")
            self.assertNotIn("LogPixels", restored)
            self.assertIn('"Later"="preserve"', restored)
            self.assertEqual(record["status"], "restored")

    def test_restores_original_present_value(self):
        with tempfile.TemporaryDirectory() as root:
            library = pathlib.Path(root) / "library"
            pfx = library / "steamapps" / "compatdata" / "10" / "pfx"
            pfx.mkdir(parents=True)
            reg = pfx / "user.reg"
            reg.write_text(HEADER + DESKTOP + '"LogPixels"=dword:00000078\n',
                           encoding="utf-8")
            record = {}
            DPI.reconcile_one("alice", "10", str(library), 200, record,
                              str(pathlib.Path(root) / "backups"))
            DPI.reconcile_one("alice", "10", str(library), None, record,
                              str(pathlib.Path(root) / "backups"))
            self.assertIn('"LogPixels"=dword:00000078',
                          reg.read_text(encoding="utf-8"))

    def test_duplicate_libraries_keep_independent_original_values(self):
        with tempfile.TemporaryDirectory() as root:
            backup = pathlib.Path(root) / "backups"
            records, registries = [], []
            for name, value in (("first", "00000078"), ("second", "00000090")):
                library = pathlib.Path(root) / name
                pfx = library / "steamapps" / "compatdata" / "10" / "pfx"
                pfx.mkdir(parents=True)
                reg = pfx / "user.reg"
                reg.write_text(HEADER + DESKTOP + f'"LogPixels"=dword:{value}\n',
                               encoding="utf-8")
                record = {"library": str(library)}
                DPI.reconcile_one("alice", "10", str(library), 200, record,
                                  str(backup))
                records.append((library, record)); registries.append((reg, value))
            for library, record in records:
                DPI.reconcile_one("alice", "10", str(library), None, record,
                                  str(backup))
            for reg, value in registries:
                self.assertIn(f'"LogPixels"=dword:{value}',
                              reg.read_text(encoding="utf-8"))
            self.assertNotEqual(records[0][1]["backup"], records[1][1]["backup"])


class StateTests(unittest.TestCase):
    def test_legacy_single_library_state_migrates(self):
        record = {"managed": True, "original_recorded": True,
                  "original_present": False, "backup": "/old/backup"}
        instances = DPI.ensure_instances(record, ["/games/library"])
        self.assertEqual(len(instances), 1)
        migrated = next(iter(instances.values()))
        self.assertTrue(migrated["managed"])
        self.assertEqual(migrated["backup"], "/old/backup")

    def test_uninstall_blockers_include_each_managed_instance(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = pathlib.Path(root) / "state.json"
            state = {"version": 1, "users": {"alice": {"10": {"instances": {
                    "one": {"library": "/one", "managed": True, "status": "current"},
                    "two": {"library": "/two", "managed": True, "status": "applied"}
            }}}}}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            blockers = DPI.uninstall_blockers(str(state_path))
            self.assertEqual({item["library"] for item in blockers}, {"/one", "/two"})


if __name__ == "__main__":
    unittest.main()
