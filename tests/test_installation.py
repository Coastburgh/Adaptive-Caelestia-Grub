import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


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


INSTALL = (ROOT / 'scripts/install.sh').read_text()
UNINSTALL = (ROOT / 'scripts/uninstall.sh').read_text()


def python_blocks(script):
    return re.findall(r"<<'PYTHON'[^\n]*\n(.*?)\nPYTHON", script, re.S)


@unittest.skipUnless(sys.platform.startswith('linux'), 'The installer targets Linux only')
class DeploymentSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.destination = self.root / 'destination'
        self.source.mkdir()
        self.destination.mkdir()
        self.helper = types.ModuleType('deployment')
        exec(python_blocks(INSTALL)[1], self.helper.__dict__)

    def copy(self, budget=None):
        fd = self.helper.open_directory(str(self.source))
        try:
            self.helper.copy_assets(fd, str(self.destination), os.getuid(),
                                    budget if budget is not None else [512, 256 * 1024 * 1024])
        finally:
            os.close(fd)

    def test_regular_assets_and_icons_are_copied(self):
        (self.source / 'theme.txt').write_text('theme')
        (self.source / 'font.pf2').write_bytes(b'font')
        (self.source / 'icons').mkdir()
        (self.source / 'icons/linux.png').write_bytes(b'icon')
        self.copy()
        self.assertEqual((self.destination / 'theme.txt').read_text(), 'theme')
        self.assertEqual((self.destination / 'icons/linux.png').read_bytes(), b'icon')
        self.assertEqual((self.destination / 'font.pf2').stat().st_mode & 0o777, 0o644)

    def test_empty_source_copies_nothing(self):
        self.copy()
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_symlink_files_and_directories_are_rejected(self):
        outside = self.root / 'outside'
        outside.write_text('original')
        for name in ['background.png', 'icons']:
            with self.subTest(name=name):
                link = self.source / name
                link.symlink_to(outside)
                with self.assertRaises(OSError):
                    self.copy()
                link.unlink()
                self.assertEqual(outside.read_text(), 'original')

    def test_symlink_source_ancestor_is_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            self.helper.open_directory(str(alias))

    def test_pinned_directory_survives_path_replacement(self):
        (self.source / 'background.png').write_bytes(b'original')
        fd = self.helper.open_directory(str(self.source))
        try:
            self.source.rename(self.root / 'original')
            self.source.symlink_to(self.root)
            self.helper.copy_assets(fd, str(self.destination), os.getuid(), [512, 1024])
        finally:
            os.close(fd)
        self.assertEqual((self.destination / 'background.png').read_bytes(), b'original')

    def test_symlink_destination_is_never_followed(self):
        outside = self.root / 'outside'
        outside.write_text('original')
        (self.source / 'background.png').write_text('replacement')
        (self.destination / 'background.png').symlink_to(outside)
        with self.assertRaises(FileExistsError):
            self.copy()
        self.assertEqual(outside.read_text(), 'original')

    def test_special_files_and_unexpected_names_are_rejected(self):
        fifo = self.source / 'background.png'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            self.copy()
        fifo.unlink()
        (self.source / 'script.sh').write_text('untrusted')
        with self.assertRaises(ValueError):
            self.copy()

    def test_nested_icon_directories_are_rejected(self):
        (self.source / 'icons/icons').mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.copy()

    def test_other_owners_are_rejected(self):
        (self.source / 'background.png').write_bytes(b'image')
        fd = self.helper.open_directory(str(self.source))
        try:
            with self.assertRaises(ValueError):
                self.helper.copy_assets(fd, str(self.destination), os.getuid() + 1, [512, 1024])
        finally:
            os.close(fd)

    def test_asset_count_and_byte_limits_are_enforced(self):
        (self.source / 'background.png').write_bytes(b'image')
        for budget in [[0, 1024], [512, 4]]:
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.copy(budget)
        with open(self.source / 'background.png', 'wb') as asset:
            asset.truncate(64 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            self.copy()

    def test_helper_requires_root_and_no_arguments(self):
        for uid, arguments in [(1000, ['helper']), (0, ['helper', 'extra'])]:
            with self.subTest(uid=uid, arguments=arguments):
                with mock.patch.object(self.helper.os, 'geteuid', return_value=uid):
                    with mock.patch.object(self.helper.sys, 'argv', arguments):
                        with self.assertRaises(ValueError):
                            self.helper.main()

    def deployment_environment(self):
        """Model root-owned boot directories without requiring root or touching /boot."""
        parent = self.root / 'boot/grub/themes'
        parent.mkdir(parents=True)
        home = self.root / 'home'
        source = home / '.local/share/adaptive-caelestia-grub/theme'
        source.mkdir(parents=True)
        code = python_blocks(INSTALL)[1].replace('"/boot/grub/themes"', repr(str(parent)))
        exec(code, self.helper.__dict__)
        self.helper.INSTALL_USER = 'test-user'
        real_lstat, real_fstat = os.lstat, os.fstat

        def lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if Path(path) in [parent, *parent.parents]:
                return types.SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)
            return info

        def fstat(fd):
            info = real_fstat(fd)
            if os.readlink('/proc/self/fd/' + str(fd)).endswith('/.adaptive-caelestia-grub.lock'):
                return types.SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o600)
            return info

        patches = [
            mock.patch.object(self.helper.os, 'geteuid', return_value=0),
            mock.patch.object(self.helper.sys, 'argv', ['helper']),
            mock.patch.object(self.helper.pwd, 'getpwnam', return_value=types.SimpleNamespace(
                pw_dir=str(home), pw_uid=os.getuid())),
            mock.patch.object(self.helper.os, 'lstat', side_effect=lstat),
            mock.patch.object(self.helper.os, 'fstat', side_effect=fstat),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return source, parent / 'adaptive-caelestia-grub'

    def test_deployment_replaces_old_links_and_cleans_staging(self):
        source, target = self.deployment_environment()
        outside = self.root / 'outside'
        outside.write_text('original')
        target.mkdir()
        (target / 'background.png').symlink_to(outside)
        (source / 'theme.txt').write_text('theme')
        (source / 'background.png').write_text('first')
        self.helper.main()
        (source / 'background.png').write_text('second')
        self.helper.main()
        self.assertEqual(outside.read_text(), 'original')
        self.assertEqual((target / 'background.png').read_text(), 'second')
        self.assertEqual(list(target.parent.glob('.adaptive-caelestia-grub-*')), [])

    def test_invalid_deployment_keeps_previous_theme(self):
        source, target = self.deployment_environment()
        target.mkdir()
        (target / 'theme.txt').write_text('previous')
        for invalid in ['missing', 'symlink']:
            with self.subTest(invalid=invalid):
                if invalid == 'symlink':
                    (source / 'theme.txt').symlink_to(target / 'theme.txt')
                with self.assertRaises((OSError, ValueError)):
                    self.helper.main()
                self.assertEqual((target / 'theme.txt').read_text(), 'previous')

    def test_failed_publish_restores_previous_theme(self):
        source, target = self.deployment_environment()
        target.mkdir()
        (target / 'theme.txt').write_text('previous')
        (source / 'theme.txt').write_text('replacement')
        rename = os.rename

        def fail_publish(src, dst):
            if Path(src).name == 'payload':
                raise OSError('Simulated publish failure')
            return rename(src, dst)

        with mock.patch.object(self.helper.os, 'rename', side_effect=fail_publish):
            with self.assertRaises(OSError):
                self.helper.main()
        self.assertEqual((target / 'theme.txt').read_text(), 'previous')


class InstallationPathSecurityTests(unittest.TestCase):
    def validate(self, prefix, mode=stat.S_IFDIR | 0o755, uid=0):
        with mock.patch.object(sys, 'argv', ['-', prefix]):
            with mock.patch('os.path.lexists', return_value=True):
                with mock.patch('os.lstat', return_value=types.SimpleNamespace(st_uid=uid, st_mode=mode)):
                    exec(python_blocks(INSTALL)[0], {})

    def test_secure_prefix_is_accepted(self):
        self.validate('/usr/local')

    def test_empty_relative_and_shell_metacharacter_prefixes_are_rejected(self):
        for prefix in ['', 'relative', '/usr/../local', '/tmp/user prefix', '/tmp/$(command)', None]:
            with self.subTest(prefix=prefix), self.assertRaises((SystemExit, TypeError)):
                self.validate(prefix)

    def test_writable_non_root_and_symlink_ancestors_are_rejected(self):
        for mode, uid in [(stat.S_IFDIR | 0o777, 0), (stat.S_IFDIR | 0o755, 1000),
                          (stat.S_IFLNK | 0o755, 0)]:
            with self.subTest(mode=mode, uid=uid), self.assertRaises(SystemExit):
                self.validate('/usr/local', mode, uid)


class ConfigurationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "user's configuration.json"
        self.hook = "export PREFIX=/usr/local; bash /home/user\\ name/sync.sh"

    def update(self, script=INSTALL, hook=None):
        arguments = [str(self.path), self.hook if hook is None else hook]
        if script == UNINSTALL:
            arguments.append('legacy hook')
        return subprocess.run([sys.executable, '-I', '-', *arguments],
                              input=python_blocks(script)[-1], text=True,
                              capture_output=True, timeout=5)

    def test_missing_configuration_and_idempotent_hooks(self):
        self.assertEqual(self.update().returncode, 0)
        self.assertEqual(self.update().returncode, 0)
        data = json.loads(self.path.read_text())
        self.assertEqual(data['wallpaper']['postHook'], self.hook)
        self.assertEqual(data['theme']['postHook'], self.hook)

    def test_invalid_configuration_is_preserved(self):
        for content in ['', '{invalid', 'null', '[]', '{"wallpaper": null}',
                        '{"theme": {"postHook": null}}']:
            for script in [INSTALL, UNINSTALL]:
                with self.subTest(content=content, uninstall=script == UNINSTALL):
                    self.path.write_text(content)
                    self.assertNotEqual(self.update(script).returncode, 0)
                    self.assertEqual(self.path.read_text(), content)

    def test_values_are_data_rather_than_python_code(self):
        marker = self.root / 'executed'
        hook = "'; open(" + repr(str(marker)) + ", 'w').close(); #"
        self.assertEqual(self.update(hook=hook).returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(json.loads(self.path.read_text())['theme']['postHook'], hook)

    def test_uninstall_removes_new_and_legacy_hooks_only(self):
        self.path.write_text(json.dumps({
            'other': True,
            'wallpaper': {'postHook': 'before && ' + self.hook + ' && after'},
            'theme': {'postHook': 'legacy hook'},
        }))
        self.assertEqual(self.update(UNINSTALL).returncode, 0)
        data = json.loads(self.path.read_text())
        self.assertEqual(data['wallpaper']['postHook'], 'before && after')
        self.assertNotIn('postHook', data['theme'])
        self.assertTrue(data['other'])

    def test_configuration_write_replaces_symlink_without_overwriting_target(self):
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        self.path.symlink_to(outside)
        self.assertEqual(self.update().returncode, 0)
        self.assertFalse(self.path.is_symlink())
        self.assertEqual(outside.read_text(), '{}')


if __name__ == "__main__":
    unittest.main()
