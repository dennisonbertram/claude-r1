#!/bin/bash
# Speak a question into the R1's microphone (ElevenLabs voice through the R1 speaker), optionally
# wrapped in a simulated side-button hold:  r1-say.sh [--ptt|--tap] "What's the weather?"
# Needs: adb forward tcp:8022 tcp:8022 (USB) and the Termux sshd.
set -euo pipefail
mode=play
case "${1:-}" in --ptt|--tap) mode=${1#--}; shift ;; esac
text="$1"
ssh -p 8022 -o ConnectTimeout=5 localhost "python3 - $(printf '%q' "$text") $mode" <<'PY'
import hashlib, json, os, subprocess, sys, time, urllib.request
text, mode = sys.argv[1], sys.argv[2]
cache = os.path.expandvars("$PREFIX/tmp/r1/say-" + hashlib.md5(text.encode()).hexdigest()[:10] + ".pcm")
if not os.path.exists(cache):
    key = open(os.path.expanduser("~/.config/r1/elevenlabs_key")).read().strip()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL?output_format=pcm_16000",
        method="POST", data=json.dumps({"text": text, "model_id": "eleven_flash_v2_5"}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"})
    open(cache, "wb").write(urllib.request.urlopen(req, timeout=30).read())
post = lambda p: subprocess.run(["curl", "-s", "-X", "POST", "localhost:8765" + p])
if mode == "ptt": post("/api/ptt/press"); time.sleep(0.45); post("/api/ptt/hold"); time.sleep(0.3)
if mode == "tap": post("/api/talk"); time.sleep(0.4)
subprocess.run(["paplay", "--raw", "--rate=16000", "--channels=1", "--format=s16le", cache])
time.sleep(0.4)
if mode == "ptt": post("/api/ptt/release")
if mode == "tap": post("/api/talk")
PY
