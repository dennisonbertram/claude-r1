#!/data/data/com.termux/files/usr/bin/bash
# Claude R1, part 2 of 2: runs inside Termux on the R1 (install.sh on your computer starts it).
# Safe to run again: every step checks whether it's already done.
#
#   bash /sdcard/Download/claude-r1/termux/setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CONF="$HOME/.config/r1"
DEBIAN="$PREFIX/var/lib/proot-distro/installed-rootfs/debian"
[ -d "$DEBIAN" ] || DEBIAN="$PREFIX/var/lib/proot-distro/containers/debian/rootfs"
step() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
in_debian() { proot-distro login debian --shared-tmp -- env PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin "$@"; }

step "Termux packages"
yes | pkg update -y >/dev/null 2>&1 || true
pkg install -y python pulseaudio mpv ffmpeg espeak sox proot-distro openssh termux-am termux-api >/dev/null
mkdir -p "$CONF" "$PREFIX/share/r1" "$PREFIX/tmp/r1/photos"
chmod 700 "$CONF"

step "Claude R1 programs"
install -m 755 "$HERE/bin/voice-server" "$HERE/bin/android-mcp" "$HERE/bin/claude" "$PREFIX/bin/"
rm -rf "$PREFIX/share/r1/voice-ui" && cp -R "$HERE/share/voice-ui" "$PREFIX/share/r1/voice-ui"
# rish (Shizuku's shell for terminal apps) — install.sh copied it out of the Shizuku app
if [ -f "$HERE/../shizuku/rish" ]; then
  install -m 755 "$HERE/../shizuku/rish" "$PREFIX/bin/rish"
  sed -i 's/RISH_APPLICATION_ID="PKG"/RISH_APPLICATION_ID="com.termux"/' "$PREFIX/bin/rish"
  grep -q 'RISH_APPLICATION_ID=' "$PREFIX/bin/rish" || sed -i '2i export RISH_APPLICATION_ID=com.termux' "$PREFIX/bin/rish"
  install -m 400 "$HERE/../shizuku/rish_shizuku.dex" "$PREFIX/bin/rish_shizuku.dex"   # Android 14 refuses a writable dex
fi

step "Let the Claude launcher start the voice server"
P="$HOME/.termux/termux.properties"
mkdir -p "$HOME/.termux" && touch "$P"
grep -q '^allow-external-apps *= *true' "$P" || echo 'allow-external-apps=true' >> "$P"
termux-reload-settings 2>/dev/null || true

step "Debian (Claude Code runs there)"
[ -d "$DEBIAN/root" ] || proot-distro install debian
DEBIAN="$PREFIX/var/lib/proot-distro/installed-rootfs/debian"
[ -d "$DEBIAN/root" ] || DEBIAN="$PREFIX/var/lib/proot-distro/containers/debian/rootfs"
in_debian bash -c 'command -v curl >/dev/null || (apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null)'
in_debian bash -c 'command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash'

step "Android tools for Claude (MCP)"
# start it once so it creates its access token, then register it with Claude Code
pgrep -f 'bin/[a]ndroid-mcp$' >/dev/null || { (setsid nohup android-mcp >/dev/null 2>&1 &); sleep 2; }
TOKEN=$(cat "$CONF/mcp_token")
in_debian bash -c "claude mcp get android >/dev/null 2>&1 || claude mcp add --transport http --scope user android \
  http://127.0.0.1:8766/mcp --header 'Authorization: Bearer $TOKEN'"
python3 - "$DEBIAN/root/.claude/settings.json" <<'PY'
import json, os, sys
p = sys.argv[1]
s = json.load(open(p)) if os.path.exists(p) else {}
allow = s.setdefault("permissions", {}).setdefault("allow", [])
if "mcp__android" not in allow:
    allow.append("mcp__android")
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(s, open(p, "w"), indent=2)
PY

step "Shizuku access for Termux"
if command -v rish >/dev/null && timeout 20 rish -c id 2>&1 | grep -q 'uid=2000'; then
  echo "Shizuku works."
else
  echo "Open the Shizuku app on the R1 and allow Termux when it asks, then run this script again."
  echo "(If Shizuku says it isn't running, start it from your computer: ./install.sh --start-shizuku)"
fi

step "Voices (optional, strongly recommended)"
if [ ! -s "$CONF/elevenlabs_key" ]; then
  echo "An ElevenLabs API key gives Claude a natural voice and accurate speech recognition."
  echo "Get one at https://elevenlabs.io (Profile → API keys). Without it, Claude uses espeak and can't hear you"
  echo "unless you install whisper.cpp yourself."
  read -rsp "Paste your ElevenLabs key (or press Enter to skip): " KEY; echo
  if [ -n "$KEY" ]; then (umask 077; printf '%s' "$KEY" > "$CONF/elevenlabs_key"); echo "Saved."; fi
fi
if [ ! -s "$CONF/email.json" ]; then
  echo
  echo "Email (optional): if Gmail is connected to your Claude account (claude.ai → Settings → Connectors) you can"
  echo "skip this. Otherwise Claude can read any mailbox over IMAP with an app password (Gmail: myaccount.google.com"
  echo "→ App passwords; iCloud, Outlook, Yahoo and Fastmail have them too). Claude reads and drafts, never sends."
  read -rp "Email address (Enter to skip): " MAIL
  if [ -n "$MAIL" ]; then
    read -rsp "App password: " MAILPW; echo
    (umask 077; python3 -c 'import json,sys; print(json.dumps({"address": sys.argv[1], "password": sys.argv[2]}))' \
      "$MAIL" "$MAILPW" > "$CONF/email.json")
    echo "Saved."
  fi
fi
if [ ! -s "$CONF/home_location" ]; then
  read -rp "Your home city, for weather and places (e.g. 'Brooklyn, New York'; Enter to skip): " HOMEAREA
  [ -n "$HOMEAREA" ] && printf '%s' "$HOMEAREA" > "$CONF/home_location"
fi

step "Log in to Claude"
if in_debian bash -c 'claude -p "reply with: ok" 2>/dev/null' | grep -qi ok; then
  echo "Already logged in."
else
  echo "Claude Code will open now. Log in with your Claude account, then type /exit to finish."
  read -rp "Press Enter to continue… " _
  claude || true
fi

step "Start"
# restart a copy left running from a previous install, so an update takes effect now
pkill -f 'bin/[v]oice-server$' 2>/dev/null && sleep 2 || true
pkill -f 'bin/[a]ndroid-mcp$' 2>/dev/null || true
(setsid nohup voice-server >>"$PREFIX/tmp/r1/voice-server.log" 2>&1 </dev/null &) || true
am start -n ai.r1.claude/.MainActivity >/dev/null 2>&1 || true
echo
echo "Done. Hold the side button and ask Claude something."
