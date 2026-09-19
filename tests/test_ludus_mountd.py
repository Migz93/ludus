import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = pathlib.Path(__file__).parents[1] / "src" / "ludus-mountd.py"
SPEC = importlib.util.spec_from_file_location("ludus_mountd", SOURCE)
MOUNTD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOUNTD)


class MountTransactionTests(unittest.TestCase):
    def test_reconcile_failure_rolls_back_binds_and_marker(self):
        with tempfile.TemporaryDirectory() as root:
            library = pathlib.Path(root) / "library"
            (library / "steamapps" / "compatdata").mkdir(parents=True)
            (library / "steamapps" / "shadercache").mkdir()
            marker = pathlib.Path(root) / "active-user"
            mounted = set()

            def is_mounted(target):
                return target in mounted

            def run(command, **_kwargs):
                if command[0] == "mount":
                    mounted.add(command[-1])
                elif command[0] == "umount":
                    mounted.discard(command[-1])
                elif command[0].endswith("ludus-proton-dpi"):
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(MOUNTD, "ACTIVE_USER", str(marker)), \
                    mock.patch.object(MOUNTD, "libraries", return_value=[str(library)]), \
                    mock.patch.object(MOUNTD, "private_dir", return_value="/private"), \
                    mock.patch.object(MOUNTD, "mounted", side_effect=is_mounted), \
                    mock.patch.object(MOUNTD.subprocess, "run", side_effect=run):
                with self.assertRaises(subprocess.CalledProcessError):
                    MOUNTD.mount_for("alice")
            self.assertEqual(mounted, set())
            self.assertFalse(marker.exists())

    def test_incomplete_rollback_keeps_active_marker(self):
        with tempfile.TemporaryDirectory() as root:
            library = pathlib.Path(root) / "library"
            (library / "steamapps" / "compatdata").mkdir(parents=True)
            (library / "steamapps" / "shadercache").mkdir()
            marker = pathlib.Path(root) / "active-user"
            mounted = set()

            def is_mounted(target):
                return target in mounted

            def run(command, **_kwargs):
                if command[0] == "mount":
                    mounted.add(command[-1])
                elif command[0] == "umount":
                    raise subprocess.CalledProcessError(1, command)
                elif command[0].endswith("ludus-proton-dpi"):
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(MOUNTD, "ACTIVE_USER", str(marker)), \
                    mock.patch.object(MOUNTD, "libraries", return_value=[str(library)]), \
                    mock.patch.object(MOUNTD, "private_dir", return_value="/private"), \
                    mock.patch.object(MOUNTD, "mounted", side_effect=is_mounted), \
                    mock.patch.object(MOUNTD.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "cleanup was incomplete"):
                    MOUNTD.mount_for("alice")
            self.assertTrue(mounted)
            self.assertEqual(marker.read_text(encoding="utf-8"), "alice\n")


if __name__ == "__main__":
    unittest.main()
