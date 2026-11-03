// Load voice-ui/index.html in headless Chrome as the R1 WebView lays it out (384x512 CSS px at DPR 1.25 = 480x640 device px), with no server, and run page-side checks.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createServer } from "node:http";
import { dirname, extname } from "node:path";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const UI = resolve(process.env.R1_UI || new URL("../../termux/share/voice-ui/index.html", import.meta.url).pathname);

const TYPES = { ".html": "text/html", ".woff2": "font/woff2", ".js": "text/javascript", ".css": "text/css" };
function serve(page) {   // the page's own folder, like voice-server does; /api/* is not served (EventSource is stubbed)
  const file = page || UI, root = dirname(file);
  const srv = createServer((q, res) => {
    const p = q.url.split("?")[0] === "/" ? "/index.html" : q.url.split("?")[0];
    const f = p === "/index.html" ? file : join(root, p);
    if (!f.startsWith(root) || !existsSync(f)) { res.writeHead(404).end(); return; }
    res.writeHead(200, { "Content-Type": TYPES[extname(f)] || "application/octet-stream" }).end(readFileSync(f));
  });
  return new Promise(r => srv.listen(0, "127.0.0.1", () => r(srv)));
}

// R1 WebView ignores the width=480 meta (useWideViewPort is off): CSS viewport is 384x512 at DPR 1.25; screenshots are 480x640 like the device.
// opts.metrics overrides the viewport; opts.url is a file path to serve (from its own folder) instead of voice-ui/index.html.
export async function openPage({ metrics, url } = {}) {
  const srv = await serve(url && resolve(url));
  const dir = mkdtempSync(join(tmpdir(), "r1ui-"));
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--remote-debugging-port=0", `--user-data-dir=${dir}`,
    "--allow-file-access-from-files", "about:blank"], { stdio: "ignore" });
  const portFile = join(dir, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await new Promise(r => setTimeout(r, 100));
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener("open", r, { once: true }));
  let id = 0; const waiting = new Map(), errors = [];
  ws.addEventListener("message", e => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description);
  });
  const send = (method, params = {}) => new Promise(r => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 384, height: 512, deviceScaleFactor: 1.25, mobile: false, ...metrics });
  // no server: stub EventSource before the page script runs, and serve /fonts from disk
  await send("Page.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "window.EventSource = class { addEventListener(){} close(){} };" });
  await send("Page.navigate", { url: `http://127.0.0.1:${srv.address().port}/` });
  const evaluate = async expr => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "eval failed");
    return r.result.result.value;
  };
  for (let i = 0; i < 100; i++) {   // wait for the page script
    try { if (await evaluate("typeof render === 'function' && document.readyState === 'complete'")) break; } catch {}
    await new Promise(r => setTimeout(r, 100));
  }
  const close = () => { ws.close(); chrome.kill(); srv.close(); try { rmSync(dir, { recursive: true, force: true }); } catch {} };
  const screenshot = async file => {   // PNG of the viewport (480x640 device px by default)
    const r = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(file, Buffer.from(r.result.data, "base64"));
  };
  return { evaluate, close, errors, screenshot };
}
