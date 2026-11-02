#!/usr/bin/env bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: This script must be run with sudo." >&2
  exit 1
fi

if [ -z "${SUDO_USER:-}" ]; then
  echo "ERROR: Could not determine the original user. Please run with sudo from a regular user account." >&2
  exit 1
fi

# Privileged commands must not resolve executables through a caller-controlled PATH.
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
PREFIX="${PREFIX:-/usr/local}"

REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
if [[ "$REAL_HOME" != /* || "$REAL_HOME" == / || "$SUDO_USER" == root ]]; then
  echo "ERROR: A regular user with an absolute home directory is required." >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

LOCAL_SHARE="$REAL_HOME/.local/share/adaptive-caelestia-grub"
GRUB_THEME_DIR="/boot/grub/themes/adaptive-caelestia-grub"
DEPLOY_SCRIPT="$PREFIX/bin/adaptive-caelestia-grub-deploy"

echo "============================================================"
echo "          Installing Adaptive Caelestia Grub"
echo "============================================================"

echo "1. Copying files to local share ($LOCAL_SHARE)..."
sudo -u "$SUDO_USER" mkdir -p "$LOCAL_SHARE/src"
sudo -u "$SUDO_USER" mkdir -p "$LOCAL_SHARE/theme"
sudo -u "$SUDO_USER" mkdir -p "$LOCAL_SHARE/scripts"

sudo -u "$SUDO_USER" cp -r "$PROJECT_ROOT/src/"* "$LOCAL_SHARE/src/"
sudo -u "$SUDO_USER" cp -r "$PROJECT_ROOT/theme/"* "$LOCAL_SHARE/theme/"
sudo -u "$SUDO_USER" cp "$PROJECT_ROOT/scripts/sync.sh" "$LOCAL_SHARE/scripts/"
sudo -u "$SUDO_USER" chmod +x "$LOCAL_SHARE/scripts/sync.sh"
echo "✓ Local files staged"

echo "2. Creating deployment hooks in $PREFIX/bin..."
# Reject writable installation ancestors and avoid following an existing helper link.
python3 -I - "$PREFIX" <<'PYTHON'
import os
import stat
import sys

prefix = sys.argv[1]
if not os.path.isabs(prefix) or any(c not in "/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in prefix):
    sys.exit("ERROR: PREFIX must be an absolute path using letters, digits, /, _ or -.")
path = "/"
for component in (prefix + "/bin").split("/"):
    if not component:
        continue
    path = os.path.join(path, component)
    if not os.path.lexists(path):
        os.mkdir(path, 0o755)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        sys.exit("ERROR: Installation directories must be owned by root and not writable by other users.")
PYTHON
DEPLOY_TEMP=$(mktemp "$PREFIX/bin/.adaptive-caelestia-grub-deploy.XXXXXX")
SUDOERS_TEMP=$(mktemp /etc/sudoers.d/.adaptive-caelestia-grub-sync.XXXXXX)
trap 'rm -f -- "$DEPLOY_TEMP" "$SUDOERS_TEMP"' EXIT
cat <<'PYTHON' > "$DEPLOY_TEMP"
#!/usr/bin/python3 -I
import fcntl
import os
import pwd
import shutil
import stat
import sys
import tempfile


def open_directory(path):
    """Pin each directory so replacing a user-controlled path cannot redirect reads."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.split("/"):
            if not component:
                continue
            if component in (".", ".."):
                raise ValueError("Invalid source path")
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def copy_assets(source, destination, uid, budget, allow_icons=True):
    with os.scandir(source) as entries:
        for entry in entries:
            name = entry.name
            if name == "icons" and allow_icons:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source)
                try:
                    os.mkdir(os.path.join(destination, name), 0o755)
                    copy_assets(child, os.path.join(destination, name), uid, budget, False)
                finally:
                    os.close(child)
                continue
            if not (name == "theme.txt" or name.endswith((".png", ".pf2"))):
                raise ValueError("Unexpected theme asset: " + name)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source)
            with os.fdopen(fd, "rb") as asset:
                info = os.fstat(asset.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != uid:
                    raise ValueError("Theme assets must be regular files owned by the installing user")
                budget[0] -= 1
                if budget[0] < 0 or info.st_size > 64 * 1024 * 1024:
                    raise ValueError("Too many assets or asset exceeds 64 MiB")
                # Read a bounded snapshot; a concurrently growing file must not fill /boot.
                content = asset.read(min(budget[1], 64 * 1024 * 1024) + 1)
                budget[1] -= len(content)
                if budget[1] < 0 or len(content) > 64 * 1024 * 1024:
                    raise ValueError("Theme exceeds the deployment size limit")
            with open(os.path.join(destination, name), "xb") as output:
                output.write(content)
            os.chmod(os.path.join(destination, name), 0o644)


def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise ValueError("Run this helper as root without arguments")
    user = pwd.getpwnam(INSTALL_USER)
    parent = "/boot/grub/themes"
    path = "/"
    for component in parent.split("/"):
        if not component:
            continue
        path = os.path.join(path, component)
        if not os.path.lexists(path):
            os.mkdir(path, 0o755)
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Deployment directories must be protected and owned by root")
    lock = os.open(parent + "/.adaptive-caelestia-grub.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lock, "wb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Unsafe deployment lock")
        fcntl.flock(handle, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix=".adaptive-caelestia-grub-", dir=parent) as staging:
            payload = staging + "/payload"
            os.mkdir(payload, 0o755)
            source = open_directory(user.pw_dir + "/.local/share/adaptive-caelestia-grub/theme")
            try:
                copy_assets(source, payload, user.pw_uid, [512, 256 * 1024 * 1024])
            finally:
                os.close(source)
            if not os.path.isfile(payload + "/theme.txt"):
                raise ValueError("Missing theme.txt")
            target = parent + "/adaptive-caelestia-grub"
            # Move the old tree aside rather than writing through its existing links.
            previous = staging + "/previous"
            if os.path.lexists(target):
                os.rename(target, previous)
            try:
                os.rename(payload, target)
            except BaseException:
                if os.path.isdir(target) and not os.path.islink(target):
                    shutil.rmtree(target)
                if os.path.lexists(previous):
                    os.rename(previous, target)
                raise


PYTHON
# Serialize the username as data, never as shell or Python source interpolation.
python3 -I - "$SUDO_USER" >> "$DEPLOY_TEMP" <<'PYTHON'
import sys
print("INSTALL_USER = " + repr(sys.argv[1]))
print('if __name__ == "__main__":')
print('    try:')
print('        main()')
print('    except (OSError, ValueError, KeyError) as error:')
print('        sys.exit("ERROR: " + str(error))')
PYTHON
chmod 755 "$DEPLOY_TEMP"
chown root:root "$DEPLOY_TEMP"
mv -fT -- "$DEPLOY_TEMP" "$DEPLOY_SCRIPT"

# Validate the drop-in before activating passwordless access; no arguments are allowed.
printf '%s ALL=(root) NOPASSWD: %s ""\n' "$SUDO_USER" "$DEPLOY_SCRIPT" > "$SUDOERS_TEMP"
chmod 440 "$SUDOERS_TEMP"
visudo -cf "$SUDOERS_TEMP"
mv -fT -- "$SUDOERS_TEMP" /etc/sudoers.d/adaptive-caelestia-grub-sync
trap - EXIT
echo "✓ Deploy script and sudoers drop-in created"

echo "3. Running initial generation and sync..."
# Export PREFIX so sync.sh can find the deploy script
sudo -u "$SUDO_USER" env PREFIX="$PREFIX" bash "$LOCAL_SHARE/scripts/sync.sh"
echo "✓ Initial sync completed"

echo "4. Updating GRUB configuration..."
if grep -q "^GRUB_THEME=" /etc/default/grub; then
    sed -i 's|^GRUB_THEME=.*|GRUB_THEME="/boot/grub/themes/adaptive-caelestia-grub/theme.txt"|' /etc/default/grub
else
    echo 'GRUB_THEME="/boot/grub/themes/adaptive-caelestia-grub/theme.txt"' >> /etc/default/grub
fi
grub-mkconfig -o /boot/grub/grub.cfg
echo "✓ GRUB updated"

echo "5. Configuring Caelestia CLI postHook..."
CLI_JSON="$REAL_HOME/.config/caelestia/cli.json"
# Quote paths for the shell and pass configuration values as data.
printf -v HOOK_CMD 'export PREFIX=%q; bash %q' "$PREFIX" "$LOCAL_SHARE/scripts/sync.sh"

sudo -u "$SUDO_USER" python3 -I - "$CLI_JSON" "$HOOK_CMD" <<'PYTHON'
import json
import os
import sys
import tempfile

try:
    path, hook = sys.argv[1:]
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
    else:
        data = {}
    if not isinstance(data, dict):
        sys.exit("ERROR: Caelestia CLI configuration must be an object.")
    for section in ['wallpaper', 'theme']:
        settings = data.setdefault(section, {})
        if not isinstance(settings, dict) or not isinstance(settings.get('postHook', ''), str):
            sys.exit("ERROR: Invalid Caelestia hook configuration.")
        if 'postHook' not in settings:
            settings['postHook'] = hook
        elif hook not in settings['postHook']:
            settings['postHook'] += ' && ' + hook

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
except (OSError, ValueError) as error:
    sys.exit("ERROR: Could not update Caelestia CLI configuration: " + str(error))
PYTHON
echo "✓ Caelestia CLI hooked"

echo ""
echo "============================================================"
echo "✅ Installation Complete!"
echo "The theme has been applied to GRUB."
echo "Whenever you change your theme in Caelestia, the GRUB background"
echo "and assets will automatically regenerate and sync in the background!"
echo "============================================================"
