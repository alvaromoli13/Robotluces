// DOM-level smoke test for web/. Loads the real index.html (and therefore app.js,
// scanner.js and the vendored js-aruco2) in jsdom and drives the UI.
//
//   npm install            # once, in tests/web/
//   npm test               # both modes
//   MODE=robot node smoke.js
//
// MODE=nobackend: nothing answers, so the page must fall back to the demo simulation.
// MODE=robot: a stub answers like backend/smartseed_robot (202 on /plan, events over
// WS /robot/progress), so the page must drive the real protocol.
const { JSDOM, VirtualConsole } = require('jsdom');
const path = require('path');

const MODE = process.env.MODE || 'nobackend';
const PAGE = path.resolve(__dirname, '../../web/index.html');

const out = [];
const errs = [];
const ok = (name, cond, extra) => out.push((cond ? 'PASS' : 'FAIL') + ' ' + name + (!cond && extra !== undefined ? ' :: ' + extra : ''));
const sleep = ms => new Promise(r => setTimeout(r, ms));

const vc = new VirtualConsole();
vc.on('jsdomError', e => {
  // jsdom has no canvas; the scanner only touches it once the camera is open.
  if (/getContext|HTMLMediaElement|Not implemented/.test(e.message)) return;
  errs.push('jsdomError: ' + e.message);
});
vc.on('error', m => errs.push('console.error: ' + m));

(async () => {
  const dom = await JSDOM.fromFile(PAGE, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.prompt = () => 'Plantilla test';
      // jsdom refuses localStorage on a file:// (opaque) origin; the page always guards
      // its storage access, but the test needs to read what was written.
      const store = new Map();
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: {
          getItem: k => (store.has(String(k)) ? store.get(String(k)) : null),
          setItem: (k, v) => store.set(String(k), String(v)),
          removeItem: k => store.delete(String(k)),
          clear: () => store.clear(),
          key: i => [...store.keys()][i] ?? null,
          get length() { return store.size; },
        },
      });
      // jsdom 29 dropped matchMedia; the page reads it to tell desktop from phone.
      window.matchMedia = query => ({ matches: /min-width: 900px/.test(query), media: query, addEventListener() {}, removeEventListener() {} });
      window.addEventListener('error', e => errs.push('window.error: ' + (e.message || e.error)));
      window.addEventListener('unhandledrejection', e => errs.push('rejection: ' + e.reason));
      const planned = [];
      window.__planned = planned;
      window.__refusePlan = null;  // set to {detail, code} to make /plan answer 422
      window.fetch = async (url, opts) => {
        if (MODE !== 'robot') throw new Error('connection refused');
        if (String(url).endsWith('/robot/status')) {
          return { ok: true, status: 200, json: async () => ({ state: 'idle', robot: 'fake', calibrated: true }) };
        }
        if (String(url).endsWith('/plan')) {
          if (window.__refusePlan) {
            const body = window.__refusePlan;
            return { ok: false, status: 422, json: async () => body };
          }
          planned.push(JSON.parse(opts.body));
          return { ok: true, status: 202, json: async () => ({ plan_id: 'p1', cells: 3 }) };
        }
        if (String(url).endsWith('/stop')) { window.__stopped = true; return { ok: true, json: async () => ({ stopped: true }) }; }
        throw new Error('connection refused');
      };
      class FakeWS {
        constructor(url) { this.url = url; window.__ws = this; }
        close() { this.closed = true; }
        send() {}
        push(msg) { if (this.onmessage) this.onmessage({ data: JSON.stringify(msg) }); }
      }
      window.WebSocket = FakeWS;
    },
  });

  const { window } = dom;
  const doc = window.document;
  const $ = id => doc.getElementById(id);
  const cellNodes = () => [...$('trayGrid').querySelectorAll('[data-cell]')];
  const filled = () => cellNodes().filter(c => c.classList.contains('filled'));
  const klass = (c, k) => c.classList.contains(k);
  await sleep(300);  // let the external scripts load

  // Stands in for a camera scan: a pixel centre for every cell of the current tray.
  window.eval(`window.smartseedScan.__fakeScan = (w, h) => {
    const { rows, cols } = window.smartseedApp.dims();
    const cells = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      cells.push({ row: r, col: c, x: Math.round((c + 0.5) * w / cols), y: Math.round((r + 0.5) * h / rows) });
    }
    Object.defineProperty(window.smartseedScan, 'lastLayout', { configurable: true, value: { cells, imageSize: [w, h], source: 'test' } });
  };`);

  // ── Boot ────────────────────────────────────────────────────────────────────
  ok('js-aruco2 vendored (window.AR)', !!window.AR);
  ok('CV vendored (window.CV)', !!window.CV);
  ok('AR.Detector builds with ARUCO_MIP_36h12',
    (() => { try { new window.AR.Detector({ dictionaryName: 'ARUCO_MIP_36h12' }); return true; } catch (e) { return 'threw: ' + e.message; } })() === true);
  ok('smartseedApp exposed', !!(window.smartseedApp && window.smartseedApp.openApp));
  ok('smartseedScan exposed', !!(window.smartseedScan && window.smartseedScan.cellCenters));
  ok('smartseedBackend exposed', !!(window.smartseedBackend && window.smartseedBackend.http));
  ok('backend ws url derived', window.smartseedBackend.ws('/progress') === 'ws://localhost:8000/progress', window.smartseedBackend.ws('/progress'));
  ok('gate shown, app hidden at boot', !$('scannerGate').hidden && $('mainApp').hidden);
  ok('box legend lists the 4 boxes', $('boxLegend').querySelectorAll('li').length === 4);
  ok('palette moved into the sidebar', !!$('seedSidebar').querySelector('.seed'));
  ok('palette cloned into the mobile dock', $('seedMobile').querySelectorAll('.seed').length === 4);
  ok('no duplicate ids in the cloned palette', $('seedMobile').querySelectorAll('[id]').length === 0);

  // ── Opening the app keeps the layout ────────────────────────────────────────
  window.smartseedApp.openApp(3, 4);
  ok('app revealed', $('scannerGate').hidden && !$('mainApp').hidden && !$('mobileSeedDock').hidden);
  ok('12 cells rendered', cellNodes().length === 12, cellNodes().length);
  ok('row labels on both sides', $('trayGrid').querySelectorAll('.row-label').length === 6);
  ok('plant disabled while empty', $('mapPlantBtn').disabled);
  ok('hint shown while empty', !$('mapPlantHint').hidden);
  ok('count copy', $('trayCount').textContent === '0 / 12 huecos', $('trayCount').textContent);

  // ── Editing ─────────────────────────────────────────────────────────────────
  cellNodes()[0].click();
  ok('click fills a cell', klass(cellNodes()[0], 'filled'));
  ok('plant enabled after one cell', !$('mapPlantBtn').disabled);
  ok('hint hidden once something is assigned', $('mapPlantHint').hidden);
  ok('layout persisted under the new key',
    (JSON.parse(window.localStorage.getItem('smartseed.lastLayout')) || {}).cells[0] === 'TOMATE',
    window.localStorage.getItem('smartseed.lastLayout'));
  cellNodes()[0].click();
  ok('clicking the same variety clears the cell', !klass(cellNodes()[0], 'filled'));

  doc.querySelectorAll('.seed')[1].click();
  ok('selecting a variety updates the legend', $('trayLegend').textContent.includes('Pimiento'), $('trayLegend').textContent);
  cellNodes()[0].click();
  ok('the newly selected variety is placed', cellNodes()[0].getAttribute('aria-label').includes('Pimiento'), cellNodes()[0].getAttribute('aria-label'));
  doc.querySelectorAll('.seed')[0].click();
  cellNodes()[0].click();
  ok('a different variety overwrites instead of clearing', cellNodes()[0].getAttribute('aria-label').includes('Tomate'), cellNodes()[0].getAttribute('aria-label'));

  const clearBadge = cellNodes()[0].querySelector('[data-clear-cell]');
  ok('filled cells offer a clear badge', !!clearBadge);
  ok('clear badge is not nested interactive content', clearBadge && clearBadge.tagName === 'SPAN' && !clearBadge.hasAttribute('role'));
  clearBadge.click();
  ok('clear badge empties the cell', !klass(cellNodes()[0], 'filled'));

  doc.querySelector('.sidebar [data-fill-all]').click();
  ok('fill-all fills every cell', filled().length === 12, filled().length);
  $('clearTrayBtn').click();
  ok('clear map empties every cell', filled().length === 0);

  // ── Templates ───────────────────────────────────────────────────────────────
  cellNodes()[0].click(); cellNodes()[5].click(); cellNodes()[11].click();
  $('saveTemplateBtn').click();
  ok('template saved into the select', [...$('templateSelect').options].some(o => o.value === 'Plantilla test'), $('templateSelect').innerHTML);
  ok('delete button appears for the saved template', !$('deleteTemplateBtn').hidden);
  $('clearTrayBtn').click();
  $('templateSelect').value = 'Plantilla test';
  $('templateSelect').dispatchEvent(new window.Event('change'));
  ok('template restores its 3 cells', filled().length === 3, filled().length);
  ok('template restores the size', $('trayCount').textContent === '3 / 12 huecos', $('trayCount').textContent);

  // ── Resizing from the camera keeps seeds in place ────────────────────────────
  window.smartseedApp.resizeTray(4, 4);
  ok('resize grows the grid', cellNodes().length === 16, cellNodes().length);
  ok('resize keeps the 3 seeds', filled().length === 3, filled().length);
  const idx = filled().map(c => Number(c.dataset.cell));
  ok('seeds kept their (row, col)', JSON.stringify(idx) === JSON.stringify([0, 5, 11]), JSON.stringify(idx));
  window.smartseedApp.resizeTray(3, 4);
  ok('shrinking back keeps what still fits', filled().length === 3, filled().length);

  // ── Planting run ────────────────────────────────────────────────────────────
  // Without a camera the plan has no pixel centres. With a backend answering, the page
  // must refuse to plant instead of pretending; with none, it simulates.
  $('mapPlantBtn').click();
  await sleep(200);
  ok('no scan + backend up: refuses to plant', MODE !== 'robot' || ($('runPanel').hidden && !$('trayActions').hidden));
  if (MODE === 'robot') ok('no scan + backend up: nothing was POSTed', window.__planned.length === 0, window.__planned.length);
  if (MODE !== 'robot') { await sleep(100); $('stopRunBtn').click(); $('stopRunBtn').click(); }

  // Pretend the tray was scanned: every cell has a pixel centre in a 1280x720 frame.
  window.smartseedScan.__fakeScan(1280, 720);

  $('mapPlantBtn').click();
  await sleep(200);
  ok('run panel replaces the actions', !$('runPanel').hidden && $('trayActions').hidden);
  if (MODE === 'robot') {
    ok('plan was POSTed', window.__planned.length === 1, window.__planned.length);
    const plan = window.__planned[window.__planned.length - 1];
    ok('plan carries the image size', plan.image_size[0] === 1280 && plan.image_size[1] === 720, JSON.stringify(plan.image_size));
    ok('plan holds only the planted cells', plan.cells.length === 3, plan.cells.length);
    ok('plan cell shape matches smartseed_robot',
      plan.cells.every(c => ['cell_index', 'row', 'col', 'color', 'u', 'v'].every(k => k in c)),
      JSON.stringify(plan.cells[0]));
    ok('plan cells carry the box colour', plan.cells[0].color === 'red', JSON.stringify(plan.cells[0]));
    ok('plan cell row/col match the index',
      plan.cells.every(c => c.row === Math.floor(c.cell_index / 4) && c.col === c.cell_index % 4),
      JSON.stringify(plan.cells));
    ok('plan carries pixel centres', plan.cells.every(c => c.u > 0 && c.v > 0), JSON.stringify(plan.cells[0]));
  } else {
    ok('nothing is POSTed with no backend', window.__planned.length === 0, window.__planned.length);
  }

  ok('editing is locked during the run', (() => {
    const before = filled().length;
    cellNodes()[2].click();
    $('clearTrayBtn').click();
    return filled().length === before;
  })());

  if (MODE === 'robot') {
    await sleep(50);
    ok('robot mode labelled from /robot/status', $('runMode').textContent === 'ROBOT SIMULADO (fake)', $('runMode').textContent);
    ok('progress socket opened on /robot/progress', window.__ws && window.__ws.url === 'ws://localhost:8000/robot/progress', window.__ws && window.__ws.url);
    window.__ws.push({ type: 'plan_started', plan_id: 'p1', total: 3, message: '3 cells' });
    window.__ws.push({ type: 'cell_started', cell_index: 0, row: 0, col: 0, color: 'red', total: 3 });
    ok('cell marked as being planted', klass(cellNodes()[0], 'planting'));
    window.__ws.push({ type: 'cell_done', cell_index: 0 });
    ok('cell marked done', klass(cellNodes()[0], 'done') && !klass(cellNodes()[0], 'planting'));
    ok('counter follows the robot', $('runCount').textContent.includes('1'), $('runCount').textContent);
    window.__ws.push({ type: 'cell_failed', cell_index: 5, message: 'gripper stayed empty after retry' });
    ok('failed cell marked', klass(cellNodes()[5], 'failed'));
    ok('failure shown in the counter', $('runCount').textContent.includes('fallidos'), $('runCount').textContent);
    window.__ws.push({ type: 'cell_done', cell_index: 11 });
    window.__ws.push({ type: 'finished', message: '2 done, 1 failed' });
    ok('run reported as finished', $('runTitle').textContent.includes('terminada'), $('runTitle').textContent);
    ok('progress bar full', $('runFill').style.width === '100%', $('runFill').style.width);
    ok('socket closed on finish', window.__ws.closed);
    $('stopRunBtn').click();
    ok('back to the editable map', $('runPanel').hidden && !$('trayActions').hidden);
    ok('editing works again', (() => { const b = filled().length; cellNodes()[1].click(); return filled().length === b + 1; })());
  } else {
    ok('demo mode labelled', $('runMode').textContent === 'MODO DEMO', $('runMode').textContent);
    ok('no socket opened without a backend', !window.__ws);
    await sleep(800);
    ok('a cell is being planted', cellNodes().some(c => klass(c, 'planting')));
    await sleep(4200);
    ok('every planned cell is done', cellNodes().filter(c => klass(c, 'done')).length === 3,
      cellNodes().filter(c => klass(c, 'done')).length);
    ok('run reported as finished', $('runTitle').textContent.includes('terminada'), $('runTitle').textContent);
    $('stopRunBtn').click();
    ok('back to the editable map', $('runPanel').hidden && !$('trayActions').hidden);
  }

  // ── A plan the robot refuses must not look like a successful run ────────────
  if (MODE === 'robot') {
    window.__refusePlan = { detail: 'cells not reachable by the arm: [11]', code: 'unreachable' };
    $('mapPlantBtn').click();
    await sleep(200);
    ok('a refused plan closes the run panel', $('runPanel').hidden && !$('trayActions').hidden);
    ok('the refusal is explained in Spanish, keeping the detail',
      $('toast').textContent.includes('fuera del alcance') && $('toast').textContent.includes('[11]'),
      $('toast').textContent);

    window.__refusePlan = { detail: 'torque is off; POST /robot/torque-on first', code: 'torque_off' };
    $('mapPlantBtn').click();
    await sleep(200);
    ok('torque_off is explained in Spanish', $('toast').textContent.includes('par de los motores'), $('toast').textContent);

    window.__refusePlan = { detail: 'a plan is already running', code: 'busy' };
    $('mapPlantBtn').click();
    await sleep(200);
    ok('busy is explained in Spanish', $('toast').textContent.includes('siembra en curso'), $('toast').textContent);
    ok('a refused plan leaves the map editable', (() => {
      const b = filled().length;
      cellNodes()[3].click();
      return filled().length === b + 1;
    })());
    cellNodes()[3].click();
    window.__refusePlan = null;
  }

  // ── Stopping mid-run ────────────────────────────────────────────────────────
  $('mapPlantBtn').click();
  await sleep(300);
  $('stopRunBtn').click();
  await sleep(100);
  ok('stop finishes the run', $('runTitle').textContent.includes('terminada'), $('runTitle').textContent);
  if (MODE === 'robot') ok('stop asked the backend to stop', window.__stopped === true);
  $('stopRunBtn').click();
  ok('closing after a stop restores the map', $('runPanel').hidden && !$('trayActions').hidden);

  ok('no page errors', errs.length === 0, JSON.stringify(errs));

  report();
})().catch(e => { console.log('HARNESS THREW:', e && (e.stack || e.message || String(e))); report(); process.exit(1); });

function report() {
  console.log('MODE=' + MODE);
  console.log(out.join('\n'));
  const fails = out.filter(l => l.startsWith('FAIL'));
  console.log('\n' + (out.length - fails.length) + '/' + out.length + ' passed');
  if (errs.length) console.log('page errors: ' + JSON.stringify(errs, null, 1));
  process.exit(fails.length ? 1 : 0);
}
