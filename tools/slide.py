#!/usr/bin/env python3
"""Render a 1920x1080 video slide: an R1 screenshot with one ringed, captioned region.
usage: slide.py out.png screenshot.png TAG "Caption" x y w h   (ring in 480x640 screen px; w=0 = no ring)"""
import base64, html, os, subprocess, sys, tempfile
out, shot, tag, cap = sys.argv[1:5]
x, y, w, h = (int(v) for v in sys.argv[5:9])
k = 1.5                                          # 480x640 screen -> 720x960 on the slide
img = base64.b64encode(open(shot, "rb").read()).decode()
ring = "" if not w else f'''<div class="ring" style="left:{x*k}px;top:{y*k}px;width:{w*k}px;height:{h*k}px"></div>'''
color = "#ff5a1f" if tag == "AFTER" else "#9a9a9a"
page = f'''<!doctype html><meta charset="utf-8"><style>
body{{margin:0;width:1920px;height:1080px;background:#0b0a09;font-family:"Inter Tight",Helvetica,sans-serif;color:#fff;overflow:hidden}}
.phone{{position:absolute;left:180px;top:60px;width:720px;height:960px;border-radius:28px;overflow:hidden;box-shadow:0 0 0 10px #222}}
.phone img{{width:720px;height:960px;display:block}}
.ring{{position:absolute;border:8px solid #fff;border-radius:18px;box-shadow:0 0 0 9999px rgba(0,0,0,.5)}}
.tag{{position:absolute;left:1000px;top:330px;font-size:44px;font-weight:800;letter-spacing:.2em;color:{color}}}
.cap{{position:absolute;left:1000px;top:400px;width:820px;font-size:96px;line-height:1;font-weight:800;letter-spacing:-.03em}}
</style><div class="phone"><img src="data:image/png;base64,{img}">{ring}</div>
<div class="tag">{html.escape(tag)}</div><div class="cap">{html.escape(cap)}</div>'''
with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
    f.write(page)
subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--hide-scrollbars",
                "--window-size=1920,1080", f"--screenshot={os.path.abspath(out)}", "file://" + f.name],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
os.unlink(f.name)
