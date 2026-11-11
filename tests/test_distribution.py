"""Smoke tests for built distributions and installed console commands."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile


MODULES = {
    "aventures2rst.py", "findpenguins.py", "fp_archive.py", "fp_config.py",
    "fp_elevation.py", "fp_parsers.py", "fp_utils.py", "fp_writers.py",
    "output_safety.py", "reminder.py", "reminders2rst.py",
}
COMMANDS = ("findpenguins", "aventures2rst", "reminder", "reminders2rst")


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wheel = Path(os.environ["SCRAPERS_TEST_WHEEL"]).resolve()
        cls.sdist = Path(os.environ["SCRAPERS_TEST_SDIST"]).resolve()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.env_dir = cls.root / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(cls.env_dir)],
            check=True,
        )
        cls.bin_dir = cls.env_dir / ("Scripts" if os.name == "nt" else "bin")
        python = cls.bin_dir / ("python.exe" if os.name == "nt" else "python")
        subprocess.run(
            [str(python), "-m", "pip", "install", str(cls.wheel)],
            check=True, cwd=cls.root,
        )
        subprocess.run([str(python), "-m", "pip", "check"], check=True, cwd=cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_command(self, command, *args, check=True):
        executable = self.bin_dir / (command + (".exe" if os.name == "nt" else ""))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [str(executable), *map(str, args)], cwd=self.root, env=env,
            text=True, capture_output=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_artifacts_contain_modules_without_private_files(self):
        with zipfile.ZipFile(self.wheel) as archive:
            wheel_files = set(archive.namelist())
        with tarfile.open(self.sdist, "r:gz") as archive:
            source_files = {name.split("/", 1)[-1] for name in archive.getnames()}
        for files in (wheel_files, source_files):
            self.assertTrue(MODULES <= files, MODULES - files)
            self.assertNotIn("profiles.json", files)
            self.assertNotIn("franklin.json", files)

    def test_all_commands_show_help_outside_checkout(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                result = self.run_command(command, "--help")
                self.assertIn("usage:", result.stdout.lower())

    def test_reminder_commands(self):
        output = self.root / "reminders"
        result = self.run_command("reminder", "--list", "Trips", "--output", output)
        self.assertIn("rem export", result.stdout)
        (output / "reminders.json").write_text(
            json.dumps([{"id": "test-id", "name": "Pack", "body": "Bring a map"}]),
            encoding="utf-8",
        )
        content = self.root / "reminder-articles"
        self.run_command("reminders2rst", "--output", output, "--content", content)
        slug = "reminder-" + hashlib.sha256(b"test-id").hexdigest()
        article = (content / (slug + ".rst")).read_text(encoding="utf-8")
        self.assertIn(":Title: Pack", article)
        self.assertIn("Bring a map", article)

    def test_force_still_protects_working_directory(self):
        result = self.run_command(
            "reminder", "--list", "Trips", "--output", self.root, "--force", check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to clear", result.stderr)

    def test_findpenguins_reports_missing_profiles(self):
        result = self.run_command("findpenguins", "missing.json", "--skip", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing.json", result.stderr)

    def test_aventures_converter(self):
        archive = self.root / "archive"
        trip_dir = archive / "traveller" / "journey"
        trip_dir.mkdir(parents=True)
        (trip_dir.parent / "profile.json").write_text(json.dumps({
            "version": 1, "user": {"uid": "traveller", "name": "Traveller"},
            "sizes": {"small": 128, "large": 1600},
        }), encoding="utf-8")
        (trip_dir / "trip.json").write_text(json.dumps({
            "version": 1, "trip": {"slug": "journey", "title": "Journey", "footprints": []},
        }), encoding="utf-8")
        content = self.root / "trip-articles"
        self.run_command("aventures2rst", "--output", archive, "--content", content)
        article = (content / "traveller" / "journey" / "trip.rst").read_text(encoding="utf-8")
        self.assertIn(":Title: Journey", article)
        result = self.run_command(
            "aventures2rst", "--output", archive, "--content", content, "--trip", "missing",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No archived trip found", result.stderr)


if __name__ == "__main__":
    unittest.main()
