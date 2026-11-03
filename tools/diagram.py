#!/usr/bin/env python3
"""Render a 1920x1080 explainer frame: a title and a row of boxes; boxes starting with '!' are the accent.
usage: diagram.py out.png TAG "Title" "box 1" "!box 2" ..."""
import html, os, subprocess, sys, tempfile
out, tag, title, *boxes = sys.argv[1:]
cells = "".join(f'<div class="b{" hot" if b.startswith("!") else ""}">{html.escape(b.lstrip("!"))}</div>'
                + ('<div class="arrow">→</div>' if i < len(boxes) - 1 else "") for i, b in enumerate(boxes))
color = "#ff5a1f" if tag == "AFTER" else "#9a9a9a"
page = f'''<!doctype html><meta charset="utf-8"><style>
body{{margin:0;width:1920px;height:1080px;background:#0b0a09;color:#fff;font-family:"Inter Tight",Helvetica,sans-serif;overflow:hidden}}
.tag{{position:absolute;left:120px;top:150px;font-size:44px;font-weight:800;letter-spacing:.2em;color:{color}}}
.t{{position:absolute;left:120px;top:215px;width:1680px;font-size:84px;line-height:1.02;font-weight:800;letter-spacing:-.03em}}
.row{{position:absolute;left:120px;right:120px;top:560px;display:flex;align-items:center;gap:24px}}
.b{{flex:1;min-height:220px;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;
   border-radius:28px;background:#22201e;font-size:40px;font-weight:750;line-height:1.15}}
.b.hot{{background:#ff5a1f;color:#120c08}}
.arrow{{font-size:56px;color:#777}}
</style><div class="tag">{html.escape(tag)}</div><div class="t">{html.escape(title)}</div><div class="row">{cells}</div>'''
with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
    f.write(page)
subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--hide-scrollbars",
                "--window-size=1920,1080", f"--screenshot={os.path.abspath(out)}", "file://" + f.name],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
os.unlink(f.name)
