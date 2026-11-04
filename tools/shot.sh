#!/bin/bash
# Screenshot the R1 into the given path (wakes the screen first).
adb shell input keyevent KEYCODE_WAKEUP
adb exec-out screencap -p > "$1"
