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
  // `preset` is what localStorage already holds when the page boots.
  const boot = preset => JSDOM.fromFile(PAGE, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.prompt = () => 'Plantilla test';
      window.__confirmAnswer = true;
      window.__confirmed = [];
      window.confirm = msg => { window.__confirmed.push(msg); return window.__confirmAnswer; };
      // jsdom refuses localStorage on a file:// (opaque) origin; the page always guards
      // its storage access, but the test needs to read what was written.
      const store = new Map(Object.entries(preset));
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
      window.__calls = [];
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
        if (String(url).includes('/robot/calibration') || String(url).includes('/robot/torque-') || String(url).includes('/robot/poses/')) {
          const path = String(url).replace(/^https?:\/\/[^/]+/, '');
          window.__calls.push({ method: (opts && opts.method) || 'GET', path, body: opts && opts.body ? JSON.parse(opts.body) : null });
          const reply = path === '/robot/calibration' ? { fitted: false, n: 0, image_size: null, points: [] }
            : path.endsWith('/fit') ? { n: 4, mean_error_mm: 1.234, max_error_mm: 2.5 } : {};
          return { ok: true, status: 200, json: async () => reply };
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

  const dom = await boot({});
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
  ok('first load seeds the original four', window.smartseedApp.seeds().map(x => x.id + ':' + x.color).join() === 'TOMATE:red,PIMIENTO:green,LIMON:yellow,BERENJENAS:purple',
    JSON.stringify(window.smartseedApp.seeds()));
  ok('the sidebar palette ends with a + tile', !!$('seedSidebar').querySelector('.seed-add') && !!$('seedMobile').querySelector('.seed-add'));
  ok('seed modal starts closed', $('seedModal').hidden);
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

  // ── Seeds: add, edit, delete through the modal ─────────────────────────────
  const fire = (el, type, init) => el.dispatchEvent(new window.KeyboardEvent(type, { bubbles: true, cancelable: true, ...init }));
  const typeInto = (el, value) => { el.value = value; el.dispatchEvent(new window.Event('input', { bubbles: true })); };
  const addTile = () => $('seedSidebar').querySelector('[data-add-seed]');
  const seedTiles = () => [...$('seedSidebar').querySelectorAll('.seed')];
  const tileOf = label => seedTiles().find(t => t.querySelector('.seed-name').textContent === label);
  const emojiOpt = e => [...$('seedEmojiGrid').querySelectorAll('[data-emoji]')].find(b => b.dataset.emoji === e);
  const colorOpt = id => $('seedColorGrid').querySelector('[data-color="' + id + '"]');
  const submit = () => $('seedForm').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));

  addTile().focus();
  addTile().click();
  ok('+ opens the modal', !$('seedModal').hidden && $('seedModalTitle').textContent === 'Nueva semilla');
  ok('modal is an accessible dialog', $('seedForm').getAttribute('role') === 'dialog' && $('seedForm').getAttribute('aria-modal') === 'true' &&
    !!doc.getElementById($('seedForm').getAttribute('aria-labelledby')));
  ok('name field is focused and labelled', doc.activeElement === $('seedName') && doc.querySelector('label[for="seedName"]'));
  ok('emoji grid offers 24 emojis', $('seedEmojiGrid').querySelectorAll('[data-emoji]').length === 24);
  ok('colour grid offers 9 swatches', $('seedColorGrid').querySelectorAll('[data-color]').length === 9);
  ok('colours already used are disabled with the seed that owns them',
    ['red', 'green', 'yellow', 'purple'].every(c => colorOpt(c).getAttribute('aria-disabled') === 'true') &&
    colorOpt('red').getAttribute('aria-label').includes('Tomate') && !!colorOpt('red').title);
  ok('a free colour is preselected', colorOpt('orange').getAttribute('aria-checked') === 'true');

  submit();
  ok('an empty name is refused', !$('seedModal').hidden && $('seedError').textContent.includes('nombre'), $('seedError').textContent);
  typeInto($('seedName'), 'x'.repeat(30));
  ok('the name is capped at 20 chars', $('seedName').maxLength === 20);
  typeInto($('seedName'), 'Albahaca');
  ok('the preview follows the name', $('seedPreview').textContent.includes('Albahaca'));
  submit();
  ok('an emoji is required', !$('seedModal').hidden && $('seedError').textContent.includes('emoji'), $('seedError').textContent);
  emojiOpt('🌿').click();
  ok('picking an emoji marks it and updates the preview', emojiOpt('🌿').getAttribute('aria-checked') === 'true' &&
    $('seedPreview').textContent.includes('🌿'));
  typeInto($('seedEmojiCustom'), 'abc');
  ok('the custom emoji field refuses plain text', $('seedError').textContent.includes('emoji'));
  typeInto($('seedEmojiCustom'), '🥑');
  ok('a pasted emoji becomes the choice', $('seedPreview').textContent.includes('🥑') && $('seedError').textContent === '');
  colorOpt('red').click();
  ok('a used colour cannot be picked', colorOpt('red').getAttribute('aria-checked') === 'false' && colorOpt('orange').getAttribute('aria-checked') === 'true');
  colorOpt('blue').click();
  ok('a free colour can be picked', colorOpt('blue').getAttribute('aria-checked') === 'true');
  submit();
  ok('saving closes the modal and returns focus to +', $('seedModal').hidden && doc.activeElement === addTile(), doc.activeElement && doc.activeElement.className);
  ok('the new seed is in the sidebar and the dock', !!tileOf('Albahaca') && [...$('seedMobile').querySelectorAll('.seed-name')].some(n => n.textContent === 'Albahaca'));
  ok('the new seed is in the box legend', $('boxLegend').textContent.includes('Albahaca') && $('boxLegend').textContent.includes('caja azul') &&
    $('boxLegend').querySelectorAll('li').length === 5);
  ok('the new seed is selected', tileOf('Albahaca').classList.contains('selected') && $('trayLegend').textContent.includes('Albahaca'), $('trayLegend').textContent);
  const stored = JSON.parse(window.localStorage.getItem('smartseed.seeds'));
  ok('seeds are persisted', stored.length === 5 && stored[4].name === 'Albahaca' && stored[4].emoji === '🥑' && stored[4].color === 'blue', JSON.stringify(stored[4]));

  // Assign it to the cell that carries the third planted cell, so the plan can be checked.
  cellNodes()[11].click();
  ok('the custom seed fills a cell', cellNodes()[11].getAttribute('aria-label').includes('Albahaca') && cellNodes()[11].getAttribute('aria-label').includes('caja azul'),
    cellNodes()[11].getAttribute('aria-label'));
  ok('the filled cell is tinted with the bowl colour', cellNodes()[11].style.getPropertyValue('--cell-strong') === '#2563c9', cellNodes()[11].style.getPropertyValue('--cell-strong'));

  // Names are user text: they must never reach the DOM as markup.
  addTile().click();
  typeInto($('seedName'), '<b>Fresa</b>');
  emojiOpt('🍓').click();
  colorOpt('white').click();
  submit();
  ok('names are escaped, not injected', !!tileOf('<b>Fresa</b>') && !$('seedSidebar').querySelector('.seed-name b'));
  const white = seedTiles().find(t => t.querySelector('.seed-name').textContent === '<b>Fresa</b>');
  ok('a white bowl gets a visible edge and a darker strong shade', /--box-edge:#[0-9a-f]{6}/.test(white.getAttribute('style')) &&
    !/--box:#fff/i.test(white.getAttribute('style')), white.getAttribute('style'));
  cellNodes()[1].click();
  ok('white seed fills a cell with a visible fill', cellNodes()[1].style.getPropertyValue('--cell-strong') !== '#ffffff' && !!cellNodes()[1].style.getPropertyValue('--cell-strong'));

  // Escape and backdrop close without saving; focus returns to the opener.
  addTile().focus();
  addTile().click();
  typeInto($('seedName'), 'No guardar');
  fire(doc, 'keydown', { key: 'Escape' });
  ok('Esc closes the modal without saving', $('seedModal').hidden && !tileOf('No guardar') && window.smartseedApp.seeds().length === 6);
  ok('Esc returns focus to the opener', doc.activeElement === addTile());
  addTile().click();
  $('seedModal').querySelector('.modal-backdrop').dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true }));
  ok('the backdrop closes the modal', $('seedModal').hidden);
  addTile().click();
  $('seedCancel').click();
  ok('Cancelar closes the modal', $('seedModal').hidden);

  // Focus stays inside the dialog.
  addTile().click();
  $('seedSave').focus();
  fire(doc, 'keydown', { key: 'Tab' });
  ok('Tab from the last control wraps to the first', doc.activeElement === $('seedCancelX'), doc.activeElement && doc.activeElement.id);
  fire(doc, 'keydown', { key: 'Tab', shiftKey: true });
  ok('Shift+Tab from the first control wraps to the last', doc.activeElement === $('seedSave'), doc.activeElement && doc.activeElement.id);
  $('seedCancel').click();

  // Edit
  const editBtn = $('seedSidebar').querySelector('[data-edit-seed]');
  ok('every tile has an edit button with a label', seedTiles().length === 6 && $('seedSidebar').querySelectorAll('[data-edit-seed]').length === 6 &&
    /^Editar /.test(editBtn.getAttribute('aria-label')));
  const albahacaId = window.smartseedApp.seeds()[4].id;
  $('seedSidebar').querySelector('[data-edit-seed="' + albahacaId + '"]').click();
  ok('edit opens the same modal prefilled', !$('seedModal').hidden && $('seedModalTitle').textContent === 'Editar semilla' && $('seedName').value === 'Albahaca' &&
    colorOpt('blue').getAttribute('aria-checked') === 'true' && !$('seedDelete').hidden);
  ok('the seed own colour stays selectable while editing', colorOpt('blue').getAttribute('aria-disabled') !== 'true');
  typeInto($('seedName'), 'Albahaca dulce');
  colorOpt('orange').click();
  submit();
  ok('edit renames the seed everywhere', !!tileOf('Albahaca dulce') && $('boxLegend').textContent.includes('Albahaca dulce'));
  ok('edit recolours the cells already planted', cellNodes()[11].getAttribute('aria-label').includes('caja naranja') && cellNodes()[11].style.getPropertyValue('--cell-strong') === '#d9660a',
    cellNodes()[11].getAttribute('aria-label'));
  $('seedSidebar').querySelector('[data-edit-seed="' + albahacaId + '"]').click();
  colorOpt('blue').click();
  submit();
  ok('colour back to blue for the plan', cellNodes()[11].getAttribute('aria-label').includes('caja azul'));

  // Delete
  const fresaId = window.smartseedApp.seeds()[5].id;
  $('seedSidebar').querySelector('[data-edit-seed="' + fresaId + '"]').click();
  window.__confirmAnswer = false;
  $('seedDelete').click();
  ok('delete asks for confirmation', window.__confirmed.length === 1 && window.__confirmed[0].includes('1 hueco'), window.__confirmed[0]);
  ok('declining keeps the seed and its cells', window.smartseedApp.seeds().length === 6 && cellNodes()[1].classList.contains('filled') && !$('seedModal').hidden);
  window.__confirmAnswer = true;
  $('seedDelete').click();
  ok('confirming deletes the seed', window.smartseedApp.seeds().length === 5 && $('seedModal').hidden);
  ok('deleting clears the cells that used it', !cellNodes()[1].classList.contains('filled') && cellNodes()[11].classList.contains('filled'));
  ok('the deleted seed leaves the palette and the legend', seedTiles().length === 5 && $('boxLegend').querySelectorAll('li').length === 5);
  ok('deletion is persisted', JSON.parse(window.localStorage.getItem('smartseed.seeds')).length === 5 &&
    !JSON.parse(window.localStorage.getItem('smartseed.lastLayout')).cells.includes(fresaId));
  ok('a still-selected seed exists after the delete', !!doc.querySelector('.seed.selected'));

  // The cell 1 is empty again, which is what the plan section below expects.
  ok('the layout still has the three planted cells', filled().length === 3, filled().length);

  // Old layouts and templates still resolve, and the stored seeds survive a reload.
  const legacy = await boot({
    'smartseed.lastLayout': JSON.stringify({ rows: 2, cols: 3, cells: ['TOMATE', 'LIMON', { name: 'BERENJENAS' }, 'PIMIENTOS', null, { name: 'Limón', emoji: '🍋' }] }),
    'smartseed.templates': JSON.stringify({ Vieja: { rows: 1, cols: 2, cells: ['BERENJENAS', 'TOMATE'] } }),
  });
  const lw = legacy.window;
  await sleep(300);
  const lcells = [...lw.document.getElementById('trayGrid').querySelectorAll('[data-cell]')];
  ok('old layout keys still resolve', lcells.filter(c => c.classList.contains('filled')).length === 5 &&
    lcells[2].getAttribute('aria-label').includes('Berenjena') && lcells[3].getAttribute('aria-label').includes('Pimiento') &&
    lcells[5].getAttribute('aria-label').includes('Limón'), lcells.map(c => c.getAttribute('aria-label')).join(' | '));
  const ts = lw.document.getElementById('templateSelect');
  ts.value = 'Vieja';
  ts.dispatchEvent(new lw.Event('change'));
  const tcells = [...lw.document.getElementById('trayGrid').querySelectorAll('[data-cell]')];
  ok('old templates still resolve', tcells.length === 2 && tcells.every(c => c.classList.contains('filled')) && tcells[0].getAttribute('aria-label').includes('Berenjena'));
  legacy.window.close();

  const again = await boot({ 'smartseed.seeds': window.localStorage.getItem('smartseed.seeds'), 'smartseed.lastLayout': window.localStorage.getItem('smartseed.lastLayout') });
  await sleep(300);
  const aw = again.window;
  ok('seeds survive a reload', aw.smartseedApp.seeds().length === 5 && aw.document.querySelectorAll('#seedSidebar .seed').length === 5);
  ok('the layout with a custom seed survives a reload', aw.document.querySelectorAll('#trayGrid .tray-cell.filled').length === 3 &&
    aw.document.querySelector('#trayGrid [data-cell="11"]').getAttribute('aria-label').includes('Albahaca'));
  again.window.close();

  const broken = await boot({ 'smartseed.seeds': '{"not":"a list"}' });
  await sleep(200);
  ok('a corrupt seed list falls back to the original four', broken.window.smartseedApp.seeds().length === 4);
  broken.window.close();

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
    ok('a custom seed sends its own colour id', plan.cells[2].color === 'blue', JSON.stringify(plan.cells[2]));
    ok('plan cell row/col match the index',
      plan.cells.every(c => c.row === Math.floor(c.cell_index / 4) && c.col === c.cell_index % 4),
      JSON.stringify(plan.cells));
    ok('plan carries pixel centres', plan.cells.every(c => c.u > 0 && c.v > 0), JSON.stringify(plan.cells[0]));
  } else {
    ok('nothing is POSTed with no backend', window.__planned.length === 0, window.__planned.length);
  }

  ok('seeds cannot be edited or deleted during the run', (() => {
    const before = window.smartseedApp.seeds().length;
    const btn = $('seedSidebar').querySelector('[data-edit-seed]');
    btn.click();
    return $('seedModal').hidden && window.smartseedApp.seeds().length === before;
  })());

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

  // ── Robot calibration from the camera view ──────────────────────────────────
  if (MODE === 'robot') {
    const video = $('cameraPreview');
    Object.defineProperty(video, 'videoWidth', { configurable: true, value: 1280 });
    Object.defineProperty(video, 'videoHeight', { configurable: true, value: 720 });
    $('calOverlay').getBoundingClientRect = () => ({ left: 10, top: 20, width: 640, height: 360 });
    const calls = () => window.__calls.map(c => c.method + ' ' + c.path);
    window.__calls.length = 0;
    $('calibrateBtn').click();
    await sleep(100);
    ok('calibrate opens its panel', !$('calPanel').hidden && $('calibrateBtn').getAttribute('aria-pressed') === 'true');
    ok('calibrate status line comes from /robot/status', $('calStatus').textContent.includes('Robot simulado') && $('calStatus').textContent.includes('calibrado'), $('calStatus').textContent);
    ok('ajustar needs 4 points', $('calFitBtn').disabled);
    $('calTorqueOffBtn').click();
    await sleep(50);
    ok('soltar brazo posts torque-off', calls().includes('POST /robot/torque-off'), calls());
    window.__calls.length = 0;
    const click = (x, y) => $('calOverlay').dispatchEvent(Object.assign(new window.Event('pointerdown'), { clientX: x, clientY: y }));
    click(10 + 320, 20 + 90);  // the middle of the width, a quarter down
    await sleep(50);
    const pt = window.__calls.find(c => c.path === '/robot/calibration/points');
    ok('a click posts the point in video pixels', pt && pt.method === 'POST' && pt.body.u === 640 && pt.body.v === 180 &&
      pt.body.image_size.join() === '1280,720', JSON.stringify(pt));
    ok('the point counter follows', $('calCount').textContent.startsWith('1 punto'), $('calCount').textContent);
    click(30, 40); click(100, 200); click(300, 300);
    await sleep(100);
    ok('four points enable ajustar', !$('calFitBtn').disabled, $('calCount').textContent);
    $('calFitBtn').click();
    await sleep(50);
    ok('ajustar posts the fit and shows the error in mm', calls().includes('POST /robot/calibration/fit') && $('calResult').textContent.includes('1.2 mm'), $('calResult').textContent);
    $('calSaveStartBtn').click(); $('calSaveHomeBtn').click(); $('calTorqueOnBtn').click(); $('calClearBtn').click();
    await sleep(100);
    ok('pose, home, torque-on and clear hit the API', ['POST /robot/poses/act_start', 'POST /robot/poses/home', 'POST /robot/torque-on', 'DELETE /robot/calibration/points'].every(c => calls().includes(c)), calls());
    ok('clearing empties the counter', $('calCount').textContent.startsWith('0 puntos'), $('calCount').textContent);
    $('calCloseBtn').click();
    ok('terminar closes the panel', $('calPanel').hidden);
  }

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
