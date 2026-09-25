#!/bin/sh
# WynnGPT installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/Hanker5/wynn-toolbox/main/install/install.sh | sh
#
# Installs into ~/WynnToolbox, adds a "WynnGPT" shortcut and a
# `wynn-toolbox` command. Run it again to update: your builds, settings and
# downloaded game data are kept.
#
# Overrides: WYNN_TOOLBOX_REPO (owner/name), WYNN_TOOLBOX_BRANCH,
# WYNN_TOOLBOX_COMMIT (install this commit; the app's updater sets it),
# WYNN_TOOLBOX_DIR (install folder), WYNN_TOOLBOX_TARBALL (URL or local file).
#
# The marker file records the installed commit, which the app's update
# checker compares with GitHub.
set -eu

REPO="${WYNN_TOOLBOX_REPO:-Hanker5/wynn-toolbox}"
BRANCH="${WYNN_TOOLBOX_BRANCH:-main}"
DIR="${WYNN_TOOLBOX_DIR:-$HOME/WynnToolbox}"
COMMIT="${WYNN_TOOLBOX_COMMIT:-}"
BIN="$HOME/.local/bin"
MARKER=".wynn-toolbox-install"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl is needed; install it with your package manager."
command -v tar >/dev/null 2>&1 || die "tar is needed; install it with your package manager."

# ---------------------------------------------------------------- uv (Python manager)
ORIG_PATH="$PATH"
export PATH="$BIN:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (it manages Python for WynnGPT)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
command -v uv >/dev/null 2>&1 || die "uv did not install; see https://docs.astral.sh/uv/"

# ---------------------------------------------------------------- the app
if [ -d "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ] && [ ! -f "$DIR/$MARKER" ]; then
  die "$DIR already exists and wasn't made by this installer.
       Move it, or choose another folder: WYNN_TOOLBOX_DIR=/some/folder sh install.sh"
fi

# Which commit: download exactly that one, so the recorded version matches the files.
if [ -z "$COMMIT" ] && [ -z "${WYNN_TOOLBOX_TARBALL:-}" ]; then
  COMMIT="$(curl -fsSL -H "Accept: application/vnd.github.sha" \
    "https://api.github.com/repos/$REPO/commits/$BRANCH" 2>/dev/null || true)"
fi
case "$COMMIT" in
  *[!0-9a-f]*|"") COMMIT="" ;;
esac
if [ -n "$COMMIT" ]; then
  TARBALL="${WYNN_TOOLBOX_TARBALL:-https://github.com/$REPO/archive/$COMMIT.tar.gz}"
else
  TARBALL="${WYNN_TOOLBOX_TARBALL:-https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz}"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
say "Downloading WynnGPT..."
case "$TARBALL" in
  http://*|https://*) curl -fsSL "$TARBALL" -o "$tmp/src.tar.gz" ||
                        die "download failed: $TARBALL" ;;
  *) cp "$TARBALL" "$tmp/src.tar.gz" ;;
esac
mkdir "$tmp/src"
tar -xzf "$tmp/src.tar.gz" -C "$tmp/src" --strip-components=1

mkdir -p "$DIR"
# Replace the app's files; keep the player's builds, settings, data and venv.
find "$DIR" -mindepth 1 -maxdepth 1 ! -name builds ! -name data ! -name .venv ! -name "$MARKER" \
  -exec rm -rf {} +
cp -R "$tmp/src/." "$DIR/"
if [ -n "$COMMIT" ]; then commit_json="\"$COMMIT\""; else commit_json=null; fi
printf '{"repo": "%s", "branch": "%s", "commit": %s, "installed_at": %s}\n' \
  "$REPO" "$BRANCH" "$commit_json" "$(date +%s)" > "$DIR/$MARKER"
mkdir -p "$DIR/builds"

cd "$DIR"
say "Setting up Python and dependencies (the first time takes a minute)..."
uv sync --no-dev --frozen --quiet
say "Downloading WynnBuilder's item data..."
"$DIR/.venv/bin/wt" fetch >/dev/null

# ---------------------------------------------------------------- launchers
mkdir -p "$BIN"
cat > "$BIN/wynn-toolbox" <<EOF
#!/bin/sh
# Starts WynnGPT (made by its installer; it updates itself from the app).
# Its output goes to builds/app.log when there is no terminal to show it.
cd "$DIR" || exit 1
if [ -t 1 ]; then exec "$DIR/.venv/bin/wt" serve "\$@"; fi
exec "$DIR/.venv/bin/wt" serve "\$@" >> "$DIR/builds/app.log" 2>&1
EOF
chmod +x "$BIN/wynn-toolbox"

where="run: wynn-toolbox"
case "$(uname -s)" in
  Darwin)
    desktop="$HOME/Desktop"
    mkdir -p "$desktop"
    cat > "$desktop/WynnGPT.command" <<EOF
#!/bin/sh
exec "$BIN/wynn-toolbox"
EOF
    chmod +x "$desktop/WynnGPT.command"
    where="double-click \"WynnGPT\" on your Desktop, or $where"
    ;;
  *)
    apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    entry="$apps/wynn-toolbox.desktop"
    cat > "$entry" <<EOF
[Desktop Entry]
Type=Application
Name=WynnGPT
Comment=AI-assisted Wynncraft builds
Exec="$BIN/wynn-toolbox"
Icon=$DIR/wynntools/web/static/logo.png
Terminal=false
Categories=Game;Utility;
EOF
    chmod +x "$entry"
    desktop="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
    if [ -d "$desktop" ]; then
      cp "$entry" "$desktop/wynn-toolbox.desktop"
      chmod +x "$desktop/wynn-toolbox.desktop"
      # GNOME only launches desktop files marked as trusted.
      gio set "$desktop/wynn-toolbox.desktop" metadata::trusted true 2>/dev/null || true
    fi
    where="open \"WynnGPT\" from your apps menu or desktop, or $where"
    ;;
esac

echo
say "Done! WynnGPT is installed in $DIR"
echo "    To start it, $where"
echo "    The first time, it will help you set up an AI assistant."
case ":$ORIG_PATH:" in
  *":$BIN:"*) ;;
  *) echo "    (Open a new terminal first if the wynn-toolbox command isn't found.)" ;;
esac
echo "    It checks for updates itself (or run this installer again)."
