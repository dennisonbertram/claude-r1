#!/bin/bash
# Print "x,y<TAB>text" for every labelled element on the R1's current screen.
adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
adb exec-out cat /sdcard/ui.xml | python3 -c '
import re, sys
for m in re.finditer(r"<node [^>]*>", sys.stdin.read()):
    n = m.group(0)
    t = re.search(r"text=\"([^\"]*)\"", n).group(1) or re.search(r"content-desc=\"([^\"]*)\"", n).group(1)
    b = re.search(r"bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"", n)
    if t and b:
        x1, y1, x2, y2 = map(int, b.groups())
        print(f"{(x1+x2)//2},{(y1+y2)//2}\t{t}")'
