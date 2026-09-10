import importlib.util
import pathlib
import tempfile
import unittest


SOURCE = pathlib.Path(__file__).parents[1] / "src" / "ludus-games.py"
SPEC = importlib.util.spec_from_file_location("ludus_games", SOURCE)
GAMES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GAMES)


def manifest(appid, name="A Game", **values):
    fields = {"appid": str(appid), "name": name, "installdir": "A Game",
              "SizeOnDisk": "12345", "LastUpdated": "1700000000", **values}
    body = "\n".join(f'\t"{key}"\t\t"{value}"' for key, value in fields.items())
    return f'"AppState"\n{{\n{body}\n}}\n'


class GameInventoryTests(unittest.TestCase):
    def library(self, root, name):
        path = pathlib.Path(root) / name
        (path / "steamapps").mkdir(parents=True)
        return path

    def write_manifest(self, library, filename_appid, body):
        (library / "steamapps" / f"appmanifest_{filename_appid}.acf").write_text(
            body, encoding="utf-8")

    def test_reads_manifest_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            library = self.library(root, "library")
            self.write_manifest(library, "10", manifest("10", "Example"))
            rows = GAMES.scan([str(library)])
        self.assertEqual(rows[0]["appid"], "10")
        self.assertEqual(rows[0]["name"], "Example")
        self.assertEqual(rows[0]["installed_bytes"], 12345)
        self.assertEqual(rows[0]["status"], "installed")
        self.assertFalse(rows[0]["component"])

    def test_marks_steam_compatibility_components(self):
        with tempfile.TemporaryDirectory() as root:
            library = self.library(root, "library")
            self.write_manifest(library, "10", manifest("10", "Proton Experimental"))
            self.write_manifest(library, "11", manifest("11", "Steam Linux Runtime 4.0"))
            rows = GAMES.scan([str(library)])
        self.assertTrue(all(row["component"] for row in rows))

    def test_reports_mismatched_and_malformed_manifests_independently(self):
        with tempfile.TemporaryDirectory() as root:
            library = self.library(root, "library")
            self.write_manifest(library, "10", manifest("11"))
            self.write_manifest(library, "12", '"AppState" { "appid" }')
            rows = GAMES.scan([str(library)])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == "error" for row in rows))
        self.assertTrue(any("does not match" in row["message"] for row in rows))

    def test_marks_every_copy_of_a_duplicate_app(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.library(root, "first")
            second = self.library(root, "second")
            self.write_manifest(first, "10", manifest("10"))
            self.write_manifest(second, "10", manifest("10"))
            rows = GAMES.scan([str(first), str(second)])
        self.assertEqual([row["status"] for row in rows], ["duplicate", "duplicate"])

    def test_missing_library_does_not_hide_valid_games(self):
        with tempfile.TemporaryDirectory() as root:
            library = self.library(root, "library")
            self.write_manifest(library, "10", manifest("10"))
            rows = GAMES.scan([str(pathlib.Path(root) / "missing"), str(library)])
        self.assertEqual({row["status"] for row in rows}, {"installed", "error"})

    def test_rejects_manifest_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            library = self.library(root, "library")
            target = pathlib.Path(root) / "outside.acf"
            target.write_text(manifest("10"), encoding="utf-8")
            (library / "steamapps" / "appmanifest_10.acf").symlink_to(target)
            rows = GAMES.scan([str(library)])
        self.assertEqual(rows[0]["status"], "error")
        self.assertIn("not a regular file", rows[0]["message"])

    def test_rejects_duplicate_keyvalues_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate KeyValues key"):
            GAMES.parse_keyvalues('"AppState" { "appid" "10" "appid" "11" }')

    def test_accepts_only_supported_image_signatures(self):
        self.assertEqual(GAMES.image_kind(b"\xff\xd8\xffdata"), "jpg")
        self.assertEqual(GAMES.image_kind(b"\x89PNG\r\n\x1a\ndata"), "png")
        self.assertEqual(GAMES.image_kind(b"GIF89a"), "")


if __name__ == "__main__":
    unittest.main()
