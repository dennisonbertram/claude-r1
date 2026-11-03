// Regression tests for the answer screen (plain + card layout, wheel, stock name). Run: node tests/ui/answers.test.mjs
import { openPage } from "./harness.mjs";

const { evaluate, close, errors } = await openPage();
let failed = 0;
const check = (name, ok, info = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${info ? "  " + info : ""}`); };

// page-side helpers (names must not collide with page globals)
await evaluate(`
  window.T = {
    show: (reply, card, you) => { S = { state: "answer", you: you || "q", reply, card: card || null, now: Date.now() / 1000 }; render(); },
    sleep: ms => new Promise(r => setTimeout(r, ms)),
    long: n => "The quick brown fox jumps over the lazy dog while the weather stays mild. ".repeat(Math.ceil(n / 75)).slice(0, n),
    list: () => ({ type: "list", title: "Things to do", items: [1, 2, 3, 4, 5, 6].map(i => ({ title: "Place number " + i, detail: "A fine detail line " + i, value: "$" + i })) }),
  };
  true`);

// ---- A1: card after a scrolling plain answer is bounded by .convo
{
  const r = await evaluate(`(async () => {
    T.show(T.long(900));
    const wasAuto = $("scroller").style.bottom;
    await T.sleep(100);
    T.show("Here are some places to try this weekend.", T.list());
    await T.sleep(200);
    const convo = document.querySelector(".convo").getBoundingClientRect(), box = $("scroller"), a = $("ans-a");
    const lis = [...document.querySelectorAll("#card li")];
    return { wasAuto, bottom: box.style.bottom, boxH: box.clientHeight, convoH: document.querySelector(".convo").clientHeight,
      capBottom: a.getBoundingClientRect().bottom, convoBottom: convo.bottom, capH: a.clientHeight,
      lh: parseFloat(getComputedStyle(a).lineHeight), lastLi: lis.length ? lis[lis.length - 1].getBoundingClientRect().bottom : 0 };
  })()`);
  check("setup: long plain answer set bottom:auto", r.wasAuto === "auto", `bottom=${r.wasAuto}`);
  check("card after scrolling plain answer: scroller.style.bottom cleared", r.bottom === "", `bottom=${JSON.stringify(r.bottom)}`);
  check("card after scrolling plain answer: scroller within convo", r.boxH <= r.convoH, `${r.boxH} <= ${r.convoH}`);
  check("card after scrolling plain answer: caption inside convo", r.capBottom <= r.convoBottom + 1, `${r.capBottom} <= ${r.convoBottom}`);
  check("card after scrolling plain answer: caption has a line", r.capH >= r.lh - 1, `${r.capH} >= ${r.lh}`);
  check("card after scrolling plain answer: last row inside convo", r.lastLi <= r.convoBottom + 1, `${r.lastLi} <= ${r.convoBottom}`);
}

// ---- A1 must-stay-green: whole lines for plain answers, scroll kept on re-render, card then plain
{
  const r = await evaluate(`(async () => {
    const out = {};
    const chk = () => { const a = $("ans-a"), b = $("scroller"), lh = parseFloat(getComputedStyle(a).lineHeight);
      const k = (parseFloat(b.style.height) - a.offsetTop) / lh; return { k, whole: Math.abs(k - Math.round(k)) < 0.01 && k > 0, h: b.style.height }; };
    T.show(T.long(900)); await T.sleep(100); out.a = chk();
    $("scroller").scrollTop = 150; await T.sleep(500); const before = $("scroller").scrollTop;
    render(); await T.sleep(700); out.keep = [before, $("scroller").scrollTop];
    T.show("short", T.list()); await T.sleep(100);
    T.show(T.long(900) + "!"); await T.sleep(100); out.c = chk();
    return out;
  })()`);
  check("(a) plain long answer keeps whole lines", r.a.whole, `height=${r.a.h} k=${r.a.k}`);
  check("(b) same plain answer re-rendered keeps scrollTop", r.keep[0] > 0 && r.keep[0] === r.keep[1], `${r.keep}`);
  check("(c) card then plain long answer: whole lines apply", r.c.whole, `height=${r.c.h} k=${r.c.k}`);
}

// ---- A2: quick wheel turns are not lost
{
  const r = await evaluate(`(async () => {
    T.show(T.long(1300)); await T.sleep(100);
    const b = $("scroller"), lh = parseFloat(getComputedStyle($("ans-a")).lineHeight);
    r1Key("down"); await T.sleep(800); r1Key("down"); await T.sleep(800);
    const p = b.scrollTop;
    for (let i = 0; i < 3; i++) { r1Key("down"); await T.sleep(40); }
    await T.sleep(900);
    return { p, now: b.scrollTop, lh, max: b.scrollHeight - b.clientHeight };
  })()`);
  const want = Math.min(r.max, r.p + 9 * r.lh);
  check("quick wheel turns are not lost", Math.abs(r.now - want) <= 2, `scrollTop=${r.now} want=${want.toFixed(1)} (p=${r.p}, max=${r.max})`);
}
{
  const r = await evaluate(`(async () => {
    T.show("A short caption for the list.", T.list()); await T.sleep(200);
    const convo = document.querySelector(".convo"), b = $("scroller");
    r1Key("down"); await T.sleep(200);                      // expand
    const expanded = convo.classList.contains("expanded");
    for (let i = 0; i < 6; i++) { r1Key("down"); await T.sleep(800); }
    const atEnd = b.scrollTop;
    for (let i = 0; i < 3; i++) { r1Key("up"); await T.sleep(40); }
    await T.sleep(900);
    const mid = b.scrollTop;
    r1Key("up"); await T.sleep(900);                         // may still be scrolling to the top
    r1Key("up"); await T.sleep(300);                         // at the top: collapse
    return { expanded, atEnd, mid, top: b.scrollTop, still: convo.classList.contains("expanded") };
  })()`);
  check("card: first down expands", r.expanded);
  check("card: quick ups from the bottom, then one more up, collapse", !r.still, `atEnd=${r.atEnd} mid=${r.mid} top=${r.top} expanded=${r.still}`);
}

// ---- A3: stock name stays on one line
{
  const r = await evaluate(`(async () => {
    T.show("Berkshire.", { type: "stock", symbol: "BRK.A", name: "Berkshire Hathaway Inc. Class A Common Stock Holdings Corporation International", price: "$712,345", change: "+1,234", percent: "0.17%", points: [1, 2, 3, 2, 4] });
    await T.sleep(200);
    const n = document.querySelector("#card .row").children[1], sym = document.querySelector("#card .row").children[0];
    const cs = getComputedStyle(n), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.25;   // "normal" line height
    return { h: n.offsetHeight, lh, sw: n.scrollWidth, cw: n.clientWidth, symW: sym.getBoundingClientRect().width, symSW: sym.scrollWidth };
  })()`);
  check("stock name is one line", r.h < r.lh * 1.5, `h=${r.h} lh=${r.lh}`);
  check("stock name is ellipsized", r.sw > r.cw, `scrollWidth=${r.sw} clientWidth=${r.cw}`);
  check("stock symbol not squeezed", r.symW >= r.symSW - 1, `w=${r.symW} sw=${r.symSW}`);
}

check("no page errors", errors.length === 0, errors.join("; "));
close();
console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
