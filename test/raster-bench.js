#!/usr/bin/env node
/* Raster cost of the board, measured with Chromium's own microbenchmark.
 *
 * requestAnimationFrame cadence cannot see raster: in headless it ticks on a
 * BeginFrame timer whether or not rasterisation kept up, which is why two
 * variants differing by 578,921px2 of filtered area produced identical frame
 * times. chrome.gpuBenchmarking.runMicroBenchmark("rasterize_and_record_micro")
 * is what Chromium's own perf suite uses, and it reports rasterize_time_ms.
 *
 *   node raster-bench.js <url>
 */
'use strict';

const CHROME = '/nix/store/4vv4mnj1qp9m4k0lgxcnxsyvdlf4i1r7-ungoogled-chromium-152.0.7977.82/bin/chromium';
const { spawn } = require('child_process');
const url = process.argv[2];
if (!url) { console.error('usage: raster-bench.js <url>'); process.exit(2); }

const port = 9333 + Math.floor(Math.random() * 400);
const child = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-sandbox',
  '--enable-gpu-benchmarking',
  '--user-data-dir=/tmp/chrome-raster-' + port,
  '--remote-debugging-port=' + port,
  '--window-size=390,844',
  url
], { stdio: ['ignore', 'ignore', 'pipe'] });

let done = false;
function finish(code, msg) {
  if (done) return;
  done = true;
  if (msg) console.log(msg);
  try { child.kill(); } catch (_) {}
  setTimeout(() => process.exit(code), 150);
}
setTimeout(() => finish(3, 'TIMEOUT: no result in 60s'), 60000);

async function targetWs() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch('http://127.0.0.1:' + port + '/json/list');
      const pages = (await r.json()).filter(t => t.type === 'page' && t.webSocketDebuggerUrl);
      if (pages.length) return pages[0].webSocketDebuggerUrl;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('devtools never came up on ' + port);
}

(async () => {
  const ws = new WebSocket(await targetWs());
  let id = 0;
  const waiting = new Map();
  const send = (method, params) => new Promise(res => {
    const n = ++id;
    waiting.set(n, res);
    ws.send(JSON.stringify({ id: n, method, params: params || {} }));
  });

  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  });

  await new Promise(res => ws.addEventListener('open', res));
  await send('Page.enable');
  await send('Runtime.enable');

  /* Wait for the board to have rendered its cards. */
  for (let i = 0; i < 60; i++) {
    const r = await send('Runtime.evaluate', {
      expression: 'document.querySelectorAll(".card").length', returnByValue: true
    });
    if (r.result && r.result.result && r.result.result.value > 0) break;
    await new Promise(r2 => setTimeout(r2, 500));
  }

  const probe = await send('Runtime.evaluate', {
    expression: `(() => {
      const cards = document.querySelectorAll('.card').length;
      const boiled = document.querySelectorAll('.card.boil-text').length;
      const area = [...document.querySelectorAll('.boil-text')].reduce((a, e) => {
        const r = e.getBoundingClientRect(); return a + r.width * r.height; }, 0);
      return JSON.stringify({ cards, boiled, filteredArea: Math.round(area),
        hasBench: typeof chrome !== 'undefined' && !!(chrome.gpuBenchmarking && chrome.gpuBenchmarking.runMicroBenchmark) });
    })()`, returnByValue: true
  });
  const info = JSON.parse(probe.result.result.value);
  if (!info.hasBench) return finish(4, 'NO BENCHMARK API: ' + JSON.stringify(info));

  const bench = await send('Runtime.evaluate', {
    awaitPromise: true, returnByValue: true, timeout: 45000,
    expression: `new Promise(resolve => {
      chrome.gpuBenchmarking.runMicroBenchmark('rasterize_and_record_micro',
        r => resolve(JSON.stringify(r)), { record_repeat_count: 1, rasterize_repeat_count: 5 });
    })`
  });

  const raw = bench.result && bench.result.result && bench.result.result.value;
  console.log(JSON.stringify({ url, probe: info, bench: raw ? JSON.parse(raw) : bench }, null, 1));
  finish(0);
})().catch(e => finish(5, 'ERROR: ' + e.message));
