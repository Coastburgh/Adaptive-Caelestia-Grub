import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NAME = "adaptive-caelestia-grub"


class InstallationNameTests(unittest.TestCase):
    def test_installation_paths_match_across_scripts(self):
        for script in ("install", "uninstall", "sync"):
            with self.subTest(script=script):
                text = (ROOT / f"scripts/{script}.sh").read_text()
                self.assertIn(f"/.local/share/{NAME}\"", text)
                self.assertIn(f'DEPLOY_SCRIPT="$PREFIX/bin/{NAME}-deploy"', text)
                self.assertIn("Adaptive Caelestia Grub", text)
                if script != "sync":
                    self.assertIn(f'GRUB_THEME_DIR="/boot/grub/themes/{NAME}"', text)
                    self.assertIn(f"/etc/sudoers.d/{NAME}-sync", text)
        installer = (ROOT / "scripts/install.sh").read_text()
        self.assertEqual(installer.count(f'/boot/grub/themes/{NAME}/theme.txt'), 2)

    def test_documentation_matches_installed_paths(self):
        text = (ROOT / "README.md").read_text()
        self.assertTrue(text.startswith("# Adaptive Caelestia Grub\n"))
        self.assertIn(f"/boot/grub/themes/{NAME}/", text)
        self.assertIn(f"~/.local/share/{NAME}/scripts/sync.sh", text)
        self.assertIn("from the previous checkout before updating", text)

    def test_sync_uses_renamed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / f".local/share/{NAME}/src"
            prefix = home / "prefix"
            (prefix / "bin").mkdir(parents=True)
            environment = dict(os.environ, HOME=str(home), PREFIX=str(prefix))

            def sync():
                return subprocess.run(["bash", str(ROOT / "scripts/sync.sh")],
                                      env=environment, text=True, capture_output=True)

            missing_source = sync()
            self.assertEqual(missing_source.returncode, 1)
            self.assertIn(str(source), missing_source.stdout)

            source.mkdir(parents=True)
            (source / "generate.py").write_text("print('Generated test assets')\n")
            missing_helper = sync()
            self.assertEqual(missing_helper.returncode, 1)
            helper = prefix / f"bin/{NAME}-deploy"
            self.assertIn(str(helper), missing_helper.stdout)

            helper.write_text("#!/bin/sh\nprintf 'Deployed test assets\\n'\n")
            helper.chmod(0o755)
            sudo = prefix / "bin/sudo"
            sudo.write_text('#!/bin/sh\nexec "$@"\n')
            sudo.chmod(0o755)
            environment["PATH"] = str(prefix / "bin") + os.pathsep + environment["PATH"]
            success = sync()
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(success.stdout.count("Deployed test assets"), 1)
            self.assertIn("Syncing Adaptive Caelestia Grub...", success.stdout)


if __name__ == "__main__":
    unittest.main()
