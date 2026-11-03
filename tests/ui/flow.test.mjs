// Flow tests: the idle clock (no "Last:" line), and the starting page (fallback.html). Run: node tests/ui/flow.test.mjs
import { openPage } from "./harness.mjs";

let failed = 0;
const check = (name, ok, info = "") => { if (!ok) failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name}${info ? "  " + info : ""}`); };

// ---- B1: the idle clock is just the clock (the owner removed the "Last:" line: too little room to be useful)
{
  const { evaluate, close, errors } = await openPage();
  const idle = (s) => evaluate(`(() => { S = ${s}; render();
    return { ready: $("ready").classList.contains("on"), text: $("ready").textContent, last: !!document.getElementById("last") }; })()`);
  let r = await idle(`{ state: "answer", you: "q", reply: "Fresh answer", now: Date.now() / 1000 }`);
  check("not idle: answer view shown", !r.ready);
  r = await idle(`{ state: "answer", you: "what day is it", reply: "It's Tuesday, November 3.", now: Date.now() / 1000 - 200 }`);
  check("idle: ready view shows", r.ready);
  check("idle: no Last line", !r.last && !/Last:|Tuesday, November 3\./.test(r.text), JSON.stringify(r.text));
  r = await idle(`{ state: "answer", you: "what day is it", reply: "", error: "No answer \\u2014 try again", now: Date.now() / 1000 - 30 }`);
  check("idle + error: no Last line", !r.last && !/Last:|what day is it/.test(r.text), JSON.stringify(r.text));
  check("no page errors (idle)", errors.length === 0, errors.join("|"));
  close();
}

// ---- B2: starting page
{
  const { evaluate, close, errors } = await openPage({ url: new URL("../../launcher/assets/fallback.html", import.meta.url).pathname });
  const st = () => evaluate(`(() => { const o = document.getElementById("opts"), s = document.getElementById("sub"), b = document.getElementById("big");
    const ob = o.getBoundingClientRect(), bb = b.getBoundingClientRect();
    return { opts: getComputedStyle(o).display, sub: getComputedStyle(s).display, subText: s.textContent, big: b.textContent,
      bigBottom: bb.bottom, optsTop: ob.top }; })()`);
  check("timings exposed: offer at 15 s, stuck at 40 s", await evaluate(`typeof OFFER_MS !== "undefined" && OFFER_MS === 15000 && STUCK_MS === 40000`));
  let r = await st();
  check("initial: buttons hidden", r.opts === "none");
  await evaluate(`offer()`);
  r = await st();
  check("offer: buttons shown", r.opts === "flex", r.opts);
  check("offer: subline hidden", r.sub === "none", r.sub);
  check("offer: headline still Starting", /Starting/.test(r.big), r.big);
  await evaluate(`stuck()`);
  r = await st();
  check("stuck: headline clear of buttons", r.bigBottom <= r.optsTop - 8, `${r.bigBottom} <= ${r.optsTop} - 8`);
  await evaluate(`restart()`);
  r = await st();
  check("restart: buttons hidden", r.opts === "none");
  check("restart: subline back", r.sub !== "none" && r.subText === "This takes a few seconds", r.subText);
  check("restart: headline Starting", /Starting/.test(r.big), r.big);
  check("no page errors (fallback)", errors.length === 0, errors.join("|"));
  close();
}

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
