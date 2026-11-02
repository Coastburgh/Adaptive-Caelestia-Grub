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
if [[ "$PREFIX" != /* || "$PREFIX" == *[^/a-zA-Z0-9_-]* ]]; then
  echo "ERROR: PREFIX must be an absolute path using letters, digits, /, _ or -." >&2
  exit 1
fi
LOCAL_SHARE="$REAL_HOME/.local/share/adaptive-caelestia-grub"
GRUB_THEME_DIR="/boot/grub/themes/adaptive-caelestia-grub"
DEPLOY_SCRIPT="$PREFIX/bin/adaptive-caelestia-grub-deploy"

echo "============================================================"
echo "         Uninstalling Adaptive Caelestia Grub"
echo "============================================================"

echo "1. Removing GRUB theme files..."
rm -rf "$GRUB_THEME_DIR"

echo "2. Removing deployment hooks and scripts..."
rm -f "$DEPLOY_SCRIPT"
rm -f /etc/sudoers.d/adaptive-caelestia-grub-sync
sudo -u "$SUDO_USER" rm -rf -- "$LOCAL_SHARE"

echo "3. Removing Caelestia CLI postHook..."
CLI_JSON="$REAL_HOME/.config/caelestia/cli.json"
# Match both safely quoted hooks and hooks written by earlier installers.
printf -v HOOK_CMD 'export PREFIX=%q; bash %q' "$PREFIX" "$LOCAL_SHARE/scripts/sync.sh"
LEGACY_HOOK_CMD="export PREFIX=$PREFIX; bash $LOCAL_SHARE/scripts/sync.sh"

sudo -u "$SUDO_USER" python3 -I - "$CLI_JSON" "$HOOK_CMD" "$LEGACY_HOOK_CMD" <<'PYTHON'
import json
import os
import sys
import tempfile

try:
    path, hook, legacy_hook = sys.argv[1:]
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            sys.exit("ERROR: Caelestia CLI configuration must be an object.")

        changed = False
        for section in ['wallpaper', 'theme']:
            if section in data:
                settings = data[section]
                if not isinstance(settings, dict) or not isinstance(settings.get('postHook', ''), str):
                    sys.exit("ERROR: Invalid Caelestia hook configuration.")
                if 'postHook' in settings:
                    hooks = settings['postHook'].split(' && ')
                    remaining = [item for item in hooks if item not in (hook, legacy_hook)]
                    if hooks != remaining:
                        if remaining:
                            settings['postHook'] = ' && '.join(remaining)
                        else:
                            del settings['postHook']
                        changed = True

        if changed:
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

echo "4. Reverting GRUB configuration..."
if grep -q "^GRUB_THEME=\"$GRUB_THEME_DIR" /etc/default/grub; then
    sed -i "s|^GRUB_THEME=\"$GRUB_THEME_DIR.*|#GRUB_THEME=|" /etc/default/grub
    grub-mkconfig -o /boot/grub/grub.cfg
    echo "✓ GRUB configuration reverted"
else
    echo "✓ No changes needed in /etc/default/grub"
fi

echo ""
echo "✅ Uninstallation Complete."
