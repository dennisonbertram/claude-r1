#!/usr/bin/env bash
# Claude R1, part 1 of 2: run on your computer with the R1 connected over USB (adb).
# It installs the apps, sets the R1 up to live in Claude, and starts part 2 inside Termux.
#
#   ./install.sh                     everything
#   ./install.sh --start-shizuku     only (re)start Shizuku, e.g. after the R1 rebooted
#   ./install.sh --launcher-apk FILE use a prebuilt launcher instead of building it
#   ./install.sh --timezone America/New_York
#   ./install.sh --shizuku-boot      restart Shizuku on the R1 without a computer (read the README's caveat first)
set -euo pipefail
cd "$(dirname "$0")"

LAUNCHER_APK="" TIMEZONE="" ONLY_SHIZUKU="" NO_TERMUX="" SHIZUKU_BOOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --launcher-apk) LAUNCHER_APK=$2; shift ;;
    --timezone) TIMEZONE=$2; shift ;;
    --start-shizuku) ONLY_SHIZUKU=1 ;;
    --no-termux) NO_TERMUX=1 ;;
    --shizuku-boot) SHIZUKU_BOOT=1 ;;  # restart Shizuku on the R1 itself after a reboot (see README first)      # copy part 2 but don't type it into Termux (run it yourself)
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
  shift
done

step() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }
sh_() { adb shell "$@" | tr -d '\r'; }

start_shizuku() {
  local dir; dir=$(sh_ pm path moe.shizuku.privileged.api | head -1 | sed 's/^package://; s/base\.apk$//')
  [ -n "$dir" ] || die "Shizuku isn't installed."
  adb shell "${dir}lib/arm64/libshizuku.so" | tail -1
}

command -v adb >/dev/null || die "adb not found. Install Android platform-tools first."
[ "$(adb get-state 2>/dev/null)" = device ] || die "No R1 found over adb. Plug it in and allow USB debugging."
SDK=$(sh_ getprop ro.build.version.sdk)
[ "$SDK" -ge 33 ] || die "This needs Android 13+ (found SDK $SDK). Flash a GSI first; see README."

if [ -n "$ONLY_SHIZUKU" ]; then start_shizuku; exit 0; fi
if [ -n "$SHIZUKU_BOOT" ]; then
  # Shizuku's own boot starter (Android 13+, no root): with this permission it turns on wireless debugging at
  # boot and starts itself. The voice server turns wireless debugging off again as soon as Shizuku is up.
  adb shell pm grant moe.shizuku.privileged.api android.permission.WRITE_SECURE_SETTINGS
  cat <<'NOTE'
Granted. One more step on the R1, once: connect to Wi-Fi, open Settings → System → Developer options → Wireless
debugging and turn it on, then open Shizuku → "Start via Wireless debugging" → Pairing, and enter the pairing
code (Wireless debugging → Pair device with pairing code). After a reboot, tap "Phone controls off · Fix" on the
Claude screen, then Start in Shizuku, and allow wireless debugging when asked.
NOTE
  exit 0
fi

# ---------------------------------------------------------------- apps
mkdir -p downloads
latest_apk() {   # latest_apk owner/repo regex -> downloads/<file>
  local url
  url=$(curl -fsSL "https://api.github.com/repos/$1/releases/latest" |
        python3 -c "import json,re,sys; r=json.load(sys.stdin); a=[x['browser_download_url'] for x in r.get('assets',[]) if re.search(sys.argv[1], x['name'])]; print(a[0] if a else '')" "$2")
  [ -n "$url" ] || return 1
  local f="downloads/$(basename "$url")"
  [ -s "$f" ] || curl -fsSL -o "$f" "$url"
  echo "$f"
}

fdroid_apk() {   # fdroid_apk package -> downloads/<file> (F-Droid's suggested version)
  local code
  code=$(curl -fsSL "https://f-droid.org/api/v1/packages/$1" | python3 -c "import json,sys; print(json.load(sys.stdin)['suggestedVersionCode'])") || return 1
  local f="downloads/$1_$code.apk"
  [ -s "$f" ] || curl -fsSL -o "$f" "https://f-droid.org/repo/$1_$code.apk"
  echo "$f"
}

step "Downloading Termux, Shizuku and KISS (latest releases)"
TERMUX=$(latest_apk termux/termux-app 'arm64-v8a\.apk$') || die "Couldn't download Termux."
SHIZUKU=$(latest_apk RikkaApps/Shizuku '\.apk$') || die "Couldn't download Shizuku."
KISS=$(fdroid_apk fr.neamar.kiss || true)
echo "$TERMUX"; echo "$SHIZUKU"; echo "${KISS:-KISS not found: skipping it, so the menu item Apps opens Settings instead}"

step "Building the Claude launcher"
if [ -z "$LAUNCHER_APK" ]; then
  launcher/build.sh >/dev/null || die "Building the launcher failed. Install the Android SDK (build-tools 34, platform 34) and JDK 17, or pass --launcher-apk."
  LAUNCHER_APK=launcher/build/claude-r1.apk
fi

step "Installing apps"
installed() { sh_ pm list packages "$1" | grep -qx "package:$1"; }
# never reinstall Termux or Shizuku over an existing copy: a copy from another source has a different
# signature, and replacing it would mean uninstalling, which deletes everything inside Termux
for pair in "com.termux:$TERMUX" "moe.shizuku.privileged.api:$SHIZUKU" ${KISS:+"fr.neamar.kiss:$KISS"}; do
  pkg=${pair%%:*} apk=${pair#*:}
  if installed "$pkg"; then echo "$pkg: already installed, keeping it"
  else printf '%s: ' "$pkg"; adb install -g "$apk" | tail -1; fi
done
printf 'ai.r1.claude: '; adb install -r -g "$LAUNCHER_APK" | tail -1

# ---------------------------------------------------------------- permissions and settings
step "Permissions"
for p in READ_EXTERNAL_STORAGE WRITE_EXTERNAL_STORAGE; do adb shell pm grant com.termux android.permission.$p 2>/dev/null || true; done
adb shell appops set com.termux MANAGE_EXTERNAL_STORAGE allow
adb shell pm grant ai.r1.claude com.termux.permission.RUN_COMMAND      # the launcher starts the voice server
for pkg in com.termux moe.shizuku.privileged.api ai.r1.claude; do adb shell dumpsys deviceidle whitelist +$pkg >/dev/null; done

step "Making Claude the R1's home screen and assistant"
adb shell cmd package set-home-activity ai.r1.claude/.MainActivity >/dev/null
adb shell cmd role add-role-holder android.app.role.HOME ai.r1.claude 0 2>/dev/null || true
adb shell cmd role add-role-holder android.app.role.ASSISTANT ai.r1.claude 0
adb shell settings put secure assistant ai.r1.claude/ai.r1.claude.MainActivity
adb shell settings put global power_button_long_press 5               # hold the side button = Claude
adb shell locksettings set-disabled true >/dev/null                    # wake straight into Claude
adb shell wm dismiss-keyguard
[ -n "$TIMEZONE" ] && adb shell cmd alarm set-timezone "$TIMEZONE"

step "Starting Shizuku (lets Claude control Android)"
start_shizuku

# ---------------------------------------------------------------- part 2, inside Termux
step "Copying the Termux part to the R1"
rm -rf downloads/bundle && mkdir -p downloads/bundle/shizuku
cp -R termux downloads/bundle/termux
unzip -p "$SHIZUKU" assets/rish > downloads/bundle/shizuku/rish
unzip -p "$SHIZUKU" assets/rish_shizuku.dex > downloads/bundle/shizuku/rish_shizuku.dex
adb shell rm -rf /sdcard/Download/claude-r1
adb push downloads/bundle /sdcard/Download/claude-r1 >/dev/null

[ -n "$NO_TERMUX" ] && { echo "Part 2 is on the R1. In Termux run: bash /sdcard/Download/claude-r1/termux/setup.sh"; exit 0; }

step "Opening Termux"
adb shell monkey -p com.termux -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
echo "Waiting for Termux to finish its first-run setup (needs Wi-Fi; can take a minute)…"
sleep 45
CMD="bash /sdcard/Download/claude-r1/termux/setup.sh"
adb shell input text "${CMD// /%s}" && adb shell input keyevent KEYCODE_ENTER
cat <<EOF

Termux on the R1 is now running part 2. If nothing happens there, type this in Termux yourself:

    $CMD

It will ask for an ElevenLabs key (optional), your home city, and a Claude login.
EOF
