import ast
import errno
import hashlib
import json
import multiprocessing
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
    def test_privileged_scripts_use_builtin_euid_for_root_check(self):
        for script in ("install", "uninstall"):
            with self.subTest(script=script):
                text = (ROOT / f"scripts/{script}.sh").read_text()
                self.assertIn('if [ "$EUID" -ne 0 ]; then', text)
                self.assertNotIn("id -u", text)

    def test_privileged_scripts_ignore_path_controlled_bash_and_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'executed'
            for name in ('bash', 'id'):
                executable = root / name
                executable.write_text('#!/bin/sh\nprintf executed > "$REVIEW_MARKER"\nexit 99\n')
                executable.chmod(0o755)
            environment = dict(os.environ, PATH=str(root), REVIEW_MARKER=str(marker))
            # Both root and non-root test runs stop before any installation or removal.
            environment.pop('SUDO_USER', None)
            environment.pop('BASH_ENV', None)
            for script in ('install', 'uninstall'):
                with self.subTest(script=script):
                    result = subprocess.run([str(ROOT / f'scripts/{script}.sh')], env=environment,
                                            text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn('ERROR:', result.stderr)
                    self.assertFalse(marker.exists())

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
        self.helper.FONT_HASHES = {name: hashlib.sha256(content).hexdigest()
                                   for name, content in [('font.pf2', b'font'), ('term.pf2', b'term')]}

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

    def test_command_characters_and_unapproved_font_names_are_rejected(self):
        for name in ['font;reboot;#.pf2', 'font;reboot;#.png', 'font\nreboot.pf2',
                     'font\nreboot.png', 'font name.png', 'font\tname.png', '$font.png',
                     'font".png', "font'.png", 'font\\name.png', '.hidden.png',
                     'font\x1b.png', 'fönt.png', 'extra.pf2', 'FONT.pf2']:
            with self.subTest(name=name):
                source = self.source / name
                source.write_bytes(b'asset')
                try:
                    with self.assertRaises(ValueError):
                        self.copy()
                    self.assertEqual(list(self.destination.iterdir()), [])
                finally:
                    source.unlink()

    def test_icons_accept_existing_distribution_names(self):
        (self.source / 'icons').mkdir()
        for source in (ROOT / 'src/icons').glob('*.png'):
            (self.source / 'icons' / source.name).write_bytes(b'icon')
        self.copy()
        self.assertEqual(sorted(path.name for path in (self.destination / 'icons').iterdir()),
                         sorted(path.name for path in (ROOT / 'src/icons').glob('*.png')))

    def test_icons_reject_fonts_and_theme_configuration(self):
        (self.source / 'icons').mkdir()
        for name in ['font.pf2', 'term.pf2', 'theme.txt']:
            with self.subTest(name=name):
                source = self.source / 'icons' / name
                source.write_bytes(b'asset')
                try:
                    with self.assertRaises(ValueError):
                        self.copy()
                finally:
                    source.unlink()
                    (self.destination / 'icons').rmdir()

    def test_fonts_match_the_installation_snapshot(self):
        for name, content in [('font.pf2', b'font'), ('term.pf2', b'term')]:
            for candidate in [content, b'', b'modified']:
                with self.subTest(name=name, content=candidate):
                    source, destination = self.source / name, self.destination / name
                    source.write_bytes(candidate)
                    try:
                        if candidate == content:
                            self.copy()
                            self.assertEqual(destination.read_bytes(), content)
                        else:
                            with self.assertRaises(ValueError):
                                self.copy()
                            self.assertFalse(destination.exists())
                    finally:
                        source.unlink()
                        destination.unlink(missing_ok=True)

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
        (source / 'font.pf2').write_bytes(b'font')
        (source / 'term.pf2').write_bytes(b'term')
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
        for invalid in ['missing', 'injection', 'modified-font', 'symlink']:
            with self.subTest(invalid=invalid):
                if invalid != 'missing':
                    (source / 'theme.txt').write_text('replacement')
                if invalid == 'injection':
                    (source / 'font;reboot;#.pf2').write_bytes(b'font')
                if invalid == 'modified-font':
                    (source / 'font.pf2').write_bytes(b'modified')
                if invalid == 'symlink':
                    (source / 'theme.txt').unlink()
                    (source / 'theme.txt').symlink_to(target / 'theme.txt')
                with self.assertRaises((OSError, ValueError)):
                    self.helper.main()
                self.assertEqual((target / 'theme.txt').read_text(), 'previous')
                for asset in source.iterdir():
                    if asset.name not in ('font.pf2', 'term.pf2'):
                        asset.unlink()
                (source / 'font.pf2').write_bytes(b'font')

    def test_missing_font_keeps_previous_theme(self):
        source, target = self.deployment_environment()
        target.mkdir()
        (target / 'theme.txt').write_text('previous')
        (source / 'theme.txt').write_text('replacement')
        for name, content in [('font.pf2', b'font'), ('term.pf2', b'term')]:
            with self.subTest(name=name):
                (source / name).unlink()
                try:
                    with self.assertRaisesRegex(ValueError, 'Missing required theme asset: ' + name):
                        self.helper.main()
                    self.assertEqual((target / 'theme.txt').read_text(), 'previous')
                finally:
                    (source / name).write_bytes(content)

    def test_disk_full_keeps_previous_theme_and_cleans_staging(self):
        source, target = self.deployment_environment()
        target.mkdir()
        (target / 'theme.txt').write_text('previous')
        (source / 'theme.txt').write_text('replacement')
        real_open = open

        def fail_write(path, mode='r', *args, **kwargs):
            if mode == 'xb':
                raise OSError(errno.ENOSPC, 'No space left on device')
            return real_open(path, mode, *args, **kwargs)

        with mock.patch('builtins.open', side_effect=fail_write):
            with self.assertRaises(OSError) as error:
                self.helper.main()
        self.assertEqual(error.exception.errno, errno.ENOSPC)
        self.assertEqual((target / 'theme.txt').read_text(), 'previous')
        self.assertEqual(list(target.parent.glob('.adaptive-caelestia-grub-*')), [])

    def test_deployment_waits_for_another_deployment_to_release_the_lock(self):
        source, target = self.deployment_environment()
        (source / 'theme.txt').write_text('replacement')
        context = multiprocessing.get_context('fork')
        receiver, sender = context.Pipe(duplex=False)
        flock = self.helper.fcntl.flock

        def deploy():
            def notify_lock(fd, operation):
                sender.send('waiting')
                flock(fd, operation)
                sender.send('acquired')

            with mock.patch.object(self.helper.fcntl, 'flock', side_effect=notify_lock):
                self.helper.main()
            sender.send('done')

        with open(target.parent / '.adaptive-caelestia-grub.lock', 'wb') as lock:
            flock(lock, self.helper.fcntl.LOCK_EX)
            process = context.Process(target=deploy)
            process.start()
            try:
                self.assertTrue(receiver.poll(5))
                self.assertEqual(receiver.recv(), 'waiting')
                self.assertFalse(receiver.poll(0.1))
                self.assertFalse(target.exists())
                flock(lock, self.helper.fcntl.LOCK_UN)
                for status in ['acquired', 'done']:
                    self.assertTrue(receiver.poll(5))
                    self.assertEqual(receiver.recv(), status)
                process.join(5)
                self.assertEqual(process.exitcode, 0)
            finally:
                flock(lock, self.helper.fcntl.LOCK_UN)
                if process.is_alive():
                    process.terminate()
                process.join(5)
                receiver.close()
                sender.close()
        self.assertEqual((target / 'theme.txt').read_text(), 'replacement')

    def test_failed_publish_restores_previous_theme(self):
        source, target = self.deployment_environment()
        target.mkdir()
        (target / 'theme.txt').write_text('previous')
        (source / 'theme.txt').write_text('replacement')
        rename = os.rename

        for error in [OSError('Simulated publish failure'), KeyboardInterrupt()]:
            def fail_publish(src, dst):
                if Path(src).name == 'payload':
                    raise error
                return rename(src, dst)

            with self.subTest(error=type(error).__name__):
                with mock.patch.object(self.helper.os, 'rename', side_effect=fail_publish):
                    with self.assertRaises(type(error)):
                        self.helper.main()
                self.assertEqual((target / 'theme.txt').read_text(), 'previous')


class FontApprovalTests(unittest.TestCase):
    def test_helper_metadata_records_only_bundled_fonts_and_serializes_username(self):
        username = "user'; raise Exception('injected'); #"
        result = subprocess.run([sys.executable, '-I', '-', username, str(ROOT / 'theme')],
                                input=python_blocks(INSTALL)[2], text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        assignments = {node.targets[0].id: ast.literal_eval(node.value)
                       for node in ast.parse(result.stdout).body if isinstance(node, ast.Assign)}
        self.assertEqual(assignments['INSTALL_USER'], username)
        self.assertEqual(assignments['FONT_HASHES'], {
            name: hashlib.sha256((ROOT / 'theme' / name).read_bytes()).hexdigest()
            for name in ('font.pf2', 'term.pf2')})

    def test_missing_fonts_prevent_helper_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', '-', 'user', directory],
                                    input=python_blocks(INSTALL)[2], text=True,
                                    capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ERROR: Could not approve bundled fonts:', result.stderr)
            self.assertEqual(result.stdout, '')


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
