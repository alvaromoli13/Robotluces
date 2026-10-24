// SmartSeed seed map: palette, tray layout, saved templates and the planting run.
// The live camera and tray localisation live in scanner.js, which drives this module
// through window.smartseedApp.
(() => {
  const $ = id => document.getElementById(id);

  // ── Backend ────────────────────────────────────────────────────────────────
  // Only the laptop wired to the arm can reach it. Published on Pages it is simply
  // unreachable, and the run falls back to a clearly labelled demo simulation.
  const BACKEND_URL = (() => {
    try { return localStorage.getItem('smartseed.backendUrl') || 'http://localhost:8000'; }
    catch (e) { return 'http://localhost:8000'; }
  })();

  window.smartseedBackend = {
    url: BACKEND_URL,
    http: path => BACKEND_URL.replace(/\/$/, '') + path,
    ws: path => BACKEND_URL.replace(/^http/, 'ws').replace(/\/$/, '') + path,
    async fetch(path, opts, ms = 4000) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), ms);
      try { return await fetch(this.http(path), { ...opts, signal: ctrl.signal }); }
      finally { clearTimeout(timer); }
    },
  };

  // ── Varieties ──────────────────────────────────────────────────────────────
  // Each variety maps to the colour of its physical box. `box` is what the robot
  // receives; the keys are stored inside saved layouts, so keep them stable.
  const SEEDS = {
    TOMATE:     { label: 'Tomate',    emoji: '🍅', box: 'red',    boxLabel: 'roja',     strong: '#c8372d', tint: '#fde3df', mid: '#f4b1a9' },
    PIMIENTO:   { label: 'Pimiento',  emoji: '🫑', box: 'green',  boxLabel: 'verde',    strong: '#2b8a4e', tint: '#dcf3e0', mid: '#a3dbb1' },
    LIMON:      { label: 'Limón',     emoji: '🍋', box: 'yellow', boxLabel: 'amarilla', strong: '#d9a400', tint: '#fff2b8', mid: '#f7dc6a' },
    BERENJENAS: { label: 'Berenjena', emoji: '🍆', box: 'purple', boxLabel: 'morada',   strong: '#7440b0', tint: '#ece2f8', mid: '#c9afe8' },
  };

  const seedKey = name => String(name || '').toUpperCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const seedMeta = name => { const k = seedKey(name); return SEEDS[k] || SEEDS[k + 'S'] || null; };

  // ── State ──────────────────────────────────────────────────────────────────
  const LAYOUT_KEY = 'smartseed.lastLayout';
  const LEGACY_LAYOUT_KEY = 'smartseed-last-layout';
  const TEMPLATES_KEY = 'smartseed.templates';
  const MAX_CELLS = 200;
  const DEMO_MS_PER_CELL = 1100;

  let selected = 'TOMATE';
  let rows = 3, cols = 3;
  let cells = [];                 // flat, row-major; each item is a variety key or null
  let run = null;                 // see startRun()
  let toastTimer = null;
  let mobileDropAt = 0;           // guards the click that follows a mobile pointerup drop

  const total = () => rows * cols;
  const filledCount = () => cells.filter(Boolean).length;

  function toast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
  }
  window.smartseedToast = toast;

  // ── Persistence ────────────────────────────────────────────────────────────

  function readJSON(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v === null ? fallback : v; }
    catch (e) { return fallback; }
  }

  function writeJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage full or blocked */ }
  }

  // Accepts both shapes: the current {rows, cols, cells} and the old flat array of
  // {name, emoji} objects saved before the tray size was stored with it.
  function normalizeLayout(raw) {
    if (Array.isArray(raw)) return { rows: 0, cols: 0, cells: raw.map(c => (c && seedMeta(c.name) ? seedKey(c.name) : null)) };
    if (!raw || !Array.isArray(raw.cells)) return null;
    return {
      rows: Number(raw.rows) || 0,
      cols: Number(raw.cols) || 0,
      cells: raw.cells.map(c => {
        if (!c) return null;
        const key = seedKey(typeof c === 'string' ? c : c.name);
        return SEEDS[key] ? key : (SEEDS[key + 'S'] ? key + 'S' : null);
      }),
    };
  }

  function saveLayout() {
    writeJSON(LAYOUT_KEY, { rows, cols, cells });
  }

  function loadTemplates() {
    const raw = readJSON(TEMPLATES_KEY, {});
    const out = {};
    Object.keys(raw || {}).forEach(name => {
      const layout = normalizeLayout(raw[name]);
      if (layout && layout.rows && layout.cols) out[name] = layout;
    });
    return out;
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  function renderLegend() {
    const m = SEEDS[selected];
    $('trayLegend').innerHTML =
      '<span class="legend-dot" style="--box:' + m.strong + '"></span>' +
      '<span>Seleccionada: <strong>' + m.emoji + ' ' + m.label + '</strong></span>';
  }

  function renderBoxLegend() {
    $('boxLegend').innerHTML = Object.values(SEEDS).map(m =>
      '<li><i class="box-dot" style="--box:' + m.strong + '"></i>' +
      '<span><strong>' + m.label + '</strong> · caja ' + m.boxLabel + '</span></li>').join('');
  }

  const cellLabel = (m, i) => (m
    ? 'Casilla ' + (i + 1) + ': ' + m.label + ', caja ' + m.boxLabel
    : 'Casilla ' + (i + 1) + ' vacía');

  // Says what the tap will actually do, which depends on the variety now selected.
  const cellTitle = (m, i) => (m
    ? m.label + ' · caja ' + m.boxLabel +
      (m === SEEDS[selected] ? ' · toca para vaciar' : ' · toca para poner ' + SEEDS[selected].label)
    : 'Casilla ' + (i + 1) + ' · toca para poner ' + SEEDS[selected].label);

  const cellInner = (m, i) =>
    '<span class="cell-emoji">' + (m ? m.emoji : '') + '</span>' +
    '<span class="cell-num">' + String(i + 1).padStart(2, '0') + '</span>' +
    '<span class="cell-state" aria-hidden="true"><svg><use href="#i-check"/></svg></span>' +
    (m ? '<span class="cell-clear" data-clear-cell="' + i + '" aria-hidden="true" title="Vaciar casilla">' +
      '<svg><use href="#i-x"/></svg></span>' : '');

  function cellHtml(key, i) {
    const m = key ? SEEDS[key] : null;
    return '<button type="button" class="tray-cell' + (m ? ' filled' : '') + '" data-cell="' + i + '"' +
      ' aria-label="' + cellLabel(m, i) + '" title="' + cellTitle(m, i) + '">' + cellInner(m, i) + '</button>';
  }

  const cellNode = i => $('trayGrid').querySelector('[data-cell="' + i + '"]');

  // Updates one cell in place. Rebuilding the whole grid on every tap would drop the
  // keyboard focus and rebuild up to 200 buttons for a single change.
  function paintCell(i) {
    const node = cellNode(i);
    if (!node) return;
    const m = cells[i] ? SEEDS[cells[i]] : null;
    node.classList.toggle('filled', !!m);
    node.classList.remove('drop-target');
    ['--cell-tint', '--cell-mid', '--cell-strong'].forEach(v => node.style.removeProperty(v));
    if (m) {
      node.style.setProperty('--cell-tint', m.tint);
      node.style.setProperty('--cell-mid', m.mid);
      node.style.setProperty('--cell-strong', m.strong);
    }
    node.setAttribute('aria-label', cellLabel(m, i));
    node.setAttribute('title', cellTitle(m, i));
    node.innerHTML = cellInner(m, i);
  }

  function updateCounts() {
    const n = filledCount();
    $('trayCount').textContent = n + ' / ' + total() + ' huecos';
    $('mapPlantBtn').disabled = n === 0;
    $('mapPlantHint').hidden = n > 0;
  }

  // Full rebuild. Only on a size change, a template load or the first render.
  function renderTray() {
    const grid = $('trayGrid');
    grid.style.setProperty('--tray-rows', rows);
    grid.style.setProperty('--tray-cols', cols);
    const html = cells.map(cellHtml);
    const rowLabel = r => '<span class="row-label" aria-hidden="true">' + (r + 1) + '</span>';
    grid.innerHTML = Array.from({ length: rows }, (_, r) =>
      rowLabel(r) + html.slice(r * cols, (r + 1) * cols).join('') + rowLabel(r)).join('');
    cells.forEach((_, i) => paintCell(i));
    updateCounts();
    if (run) paintRunState();
    if (window.smartseedScan) window.smartseedScan.layoutCells();
  }

  // ── Editing ────────────────────────────────────────────────────────────────

  function setCell(i, key) {
    if (run || i < 0 || i >= total()) return;
    cells[i] = key && SEEDS[key] ? key : null;
    saveLayout();
    paintCell(i);
    updateCounts();
  }

  function fillAll(key) {
    if (run) return;
    if (!total()) { toast('Crea primero un casillero.'); return; }
    cells = cells.map(() => key);
    saveLayout();
    cells.forEach((_, i) => paintCell(i));
    updateCounts();
    toast('Mapa completo con ' + SEEDS[key].label + '.');
  }

  function selectSeed(key) {
    if (!SEEDS[key]) return;
    selected = key;
    document.querySelectorAll('.seed').forEach(b => {
      const on = b.dataset.seed === key;
      b.classList.toggle('selected', on);
      b.setAttribute('aria-pressed', String(on));
    });
    renderLegend();
    // Only the titles change; the cells themselves stay as they are.
    $('trayGrid').querySelectorAll('[data-cell]').forEach(node => {
      const i = Number(node.dataset.cell);
      node.setAttribute('title', cellTitle(cells[i] ? SEEDS[cells[i]] : null, i));
    });
  }

  // Keep every seed at the same (row, col) when it still fits the new size.
  function setSize(nextRows, nextCols) {
    const clamp = v => Math.max(1, Math.min(20, Math.floor(Number(v) || 1)));
    nextRows = clamp(nextRows);
    nextCols = clamp(nextCols);
    if (nextRows * nextCols > MAX_CELLS) {
      toast('El casillero puede tener como máximo ' + MAX_CELLS + ' huecos.');
      return false;
    }
    const next = Array(nextRows * nextCols).fill(null);
    cells.forEach((key, i) => {
      const r = Math.floor(i / cols), c = i % cols;
      if (key && r < nextRows && c < nextCols) next[r * nextCols + c] = key;
    });
    rows = nextRows;
    cols = nextCols;
    cells = next;
    saveLayout();
    renderTray();
    return true;
  }

  function openApp(nextRows, nextCols) {
    if (!setSize(nextRows, nextCols)) return;
    $('scannerGate').hidden = true;
    $('mainApp').hidden = false;
    $('mobileSeedDock').hidden = false;
    measureDock();
  }

  // ── Templates ──────────────────────────────────────────────────────────────

  function renderTemplates(current = '') {
    const templates = loadTemplates();
    const names = Object.keys(templates).sort((a, b) => a.localeCompare(b, 'es'));
    $('templateSelect').innerHTML =
      '<option value="">' + (names.length ? 'Plantillas…' : 'Sin plantillas') + '</option>' +
      names.map(n => '<option value="' + n.replace(/"/g, '&quot;') + '"' + (n === current ? ' selected' : '') + '>' +
        n + '</option>').join('');
    $('deleteTemplateBtn').hidden = !current;
  }

  function applyTemplate(name) {
    const layout = loadTemplates()[name];
    if (!layout) return;
    rows = layout.rows;
    cols = layout.cols;
    cells = Array.from({ length: rows * cols }, (_, i) => layout.cells[i] || null);
    saveLayout();
    renderTray();
    renderTemplates(name);
    toast('Plantilla «' + name + '» cargada (' + rows + ' × ' + cols + ').');
  }

  function saveTemplate() {
    if (!filledCount()) { toast('Asigna alguna semilla antes de guardar la plantilla.'); return; }
    const name = (prompt('Nombre de la plantilla:', 'Mapa ' + rows + '×' + cols) || '').trim().slice(0, 40);
    if (!name) return;
    const templates = loadTemplates();
    templates[name] = { rows, cols, cells };
    writeJSON(TEMPLATES_KEY, templates);
    renderTemplates(name);
    toast('Plantilla «' + name + '» guardada.');
  }

  function deleteTemplate() {
    const name = $('templateSelect').value;
    if (!name) return;
    const templates = loadTemplates();
    delete templates[name];
    writeJSON(TEMPLATES_KEY, templates);
    renderTemplates('');
    toast('Plantilla «' + name + '» borrada.');
  }

  // ── Planting run ───────────────────────────────────────────────────────────
  // Wire protocol of backend/smartseed_robot (see guide.md):
  //   POST /plan {image_size:[w,h], cells:[{cell_index,row,col,color,u,v}]} -> 202 {plan_id}
  //   WS   /robot/progress  -> plan_started | cell_started | cell_done | cell_failed
  //                            | finished | stopped | error
  //   POST /stop            -> {stopped}
  // u and v are pixels in the camera frame; the backend turns them into table
  // coordinates with its camera-robot homography, so a plan needs a camera scan.

  // Pixel centre of every cell, by flat index, from the live camera or from the last
  // scan before the camera was closed. null when the tray was never scanned.
  function cellPixels() {
    const scan = window.smartseedScan;
    if (!scan) return null;
    const live = scan.cameraActive();
    const centers = live ? scan.cellCenters() : (scan.lastLayout || {}).cells;
    const size = live ? scan.imageSize() : (scan.lastLayout || {}).imageSize;
    if (!Array.isArray(centers) || !centers.length || !size || !size[0]) return null;
    const byIndex = new Map();
    centers.forEach(c => byIndex.set(c.row * cols + c.col, { u: c.x, v: c.y }));
    return { byIndex, size };
  }

  const order = () => cells.map((key, i) => (key ? i : -1)).filter(i => i >= 0);

  // null when some planted cell has no pixel centre: the robot could not reach it.
  function buildPlan(queue) {
    const pixels = cellPixels();
    if (!pixels) return null;
    const planCells = [];
    for (const i of queue) {
      const at = pixels.byIndex.get(i);
      if (!at) return null;
      planCells.push({
        cell_index: i,
        row: Math.floor(i / cols),
        col: i % cols,
        color: SEEDS[cells[i]].box,
        u: at.u,
        v: at.v,
      });
    }
    return { image_size: pixels.size, cells: planCells };
  }

  function paintRunState() {
    $('trayGrid').querySelectorAll('[data-cell]').forEach(node => {
      const i = Number(node.dataset.cell);
      const state = run ? run.state[i] : null;
      node.classList.toggle('planting', state === 'planting');
      node.classList.toggle('done', state === 'done');
      node.classList.toggle('failed', state === 'failed');
      const icon = node.querySelector('.cell-state use');
      if (icon) icon.setAttribute('href', state === 'failed' ? '#i-x' : '#i-check');
    });
  }

  function renderRun() {
    if (!run) return;
    const done = run.queue.filter(i => run.state[i] === 'done').length;
    const failed = run.queue.filter(i => run.state[i] === 'failed').length;
    const pct = run.queue.length ? Math.round(100 * (done + failed) / run.queue.length) : 0;
    $('runFill').style.width = pct + '%';
    $('runCount').innerHTML = '<strong>' + done + '</strong> / ' + run.queue.length + ' huecos sembrados' +
      (failed ? ' · ' + failed + ' fallidos' : '');
    $('runDetail').textContent = run.detail;
    $('runTitle').textContent = run.finished ? 'Siembra terminada' : 'Sembrando';
    const stop = $('stopRunBtn');
    stop.classList.toggle('danger-btn', !run.finished);
    stop.classList.toggle('secondary-btn', run.finished);
    stop.innerHTML = run.finished
      ? '<svg class="ic" aria-hidden="true"><use href="#i-check"/></svg> Volver al mapa'
      : '<svg class="ic" aria-hidden="true"><use href="#i-stop"/></svg> Parar el robot';
    paintRunState();
  }

  const cellName = i => 'fila ' + (Math.floor(i / cols) + 1) + ', columna ' + (i % cols + 1);

  function markCell(i, status, detail) {
    if (!run || !(i in run.state)) return;
    if (status === 'planting') run.queue.forEach(j => { if (run.state[j] === 'planting') run.state[j] = 'pending'; });
    run.state[i] = status;
    if (status === 'planting') run.detail = 'Sembrando ' + cellName(i);
    if (status === 'failed') run.detail = detail || 'Fallo en ' + cellName(i);
    renderRun();
  }

  function setMode(label, demo) {
    $('runMode').textContent = label;
    $('runMode').classList.toggle('demo', !!demo);
  }

  function finishRun(message, detail) {
    if (!run) return;
    run.finished = true;
    run.detail = detail || '';
    clearTimeout(run.timer);
    if (run.ws) { run.ws.onclose = null; run.ws.close(); run.ws = null; }
    renderRun();
    toast(message);
  }

  function closeRun() {
    if (!run) return;
    clearTimeout(run.timer);
    if (run.ws) { run.ws.onclose = null; run.ws.close(); }
    run = null;
    $('runPanel').hidden = true;
    $('trayActions').hidden = false;
    $('mapa-semillero').classList.remove('running');
    document.body.classList.remove('running');
    measureDock();
    renderTray();
  }

  // Published on Pages there is no robot: walk the plan locally so the flow can be shown.
  function runDemo() {
    let step = 0;
    const tick = () => {
      if (!run || run.finished) return;
      if (step >= run.queue.length) {
        finishRun('¡Siembra completada! (simulación)', 'Simulación terminada');
        return;
      }
      const i = run.queue[step];
      markCell(i, 'planting');
      run.timer = setTimeout(() => {
        if (!run || run.finished) return;
        markCell(i, 'done');
        step += 1;
        tick();
      }, DEMO_MS_PER_CELL);
    };
    tick();
  }

  function listenProgress() {
    let ws;
    try { ws = new WebSocket(window.smartseedBackend.ws('/robot/progress')); }
    catch (e) { finishRun('No se ha podido escuchar el progreso del robot.', 'Sin conexión de progreso'); return; }
    run.ws = ws;
    ws.onmessage = ev => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (!run || run.finished) return;
      switch (msg.type) {
        case 'plan_started':
          run.detail = 'El robot ha empezado el plan';
          renderRun();
          break;
        case 'cell_started':
          markCell(msg.cell_index, 'planting');
          break;
        case 'cell_done':
          markCell(msg.cell_index, 'done');
          break;
        case 'cell_failed':
          markCell(msg.cell_index, 'failed', 'Falló ' + cellName(msg.cell_index) + ': la pinza salió vacía');
          break;
        case 'finished':
          finishRun('¡Siembra completada!', msg.message || 'El robot ha terminado el plan');
          break;
        case 'stopped':
          finishRun('Siembra detenida.', msg.message || 'Parada solicitada');
          break;
        case 'error':
          finishRun('El robot ha informado de un error.', msg.message || 'Error del robot');
          break;
      }
    };
    ws.onclose = () => { if (run && !run.finished) finishRun('Se ha perdido la conexión con el robot.', 'Conexión cerrada'); };
  }

  // "fake" is the default robot mode: say so, nobody should mistake it for the arm.
  async function labelRobotMode() {
    try {
      const res = await window.smartseedBackend.fetch('/robot/status', {}, 1500);
      const st = await res.json();
      setMode(st.robot === 'real' ? 'ROBOT CONECTADO' : 'ROBOT SIMULADO (fake)', st.robot !== 'real');
    } catch (e) { setMode('ROBOT CONECTADO', false); }
  }

  // The backend answers in English with a `code`; say it in Spanish, and keep its detail
  // when there is no better wording (it carries the list of cells, the missing poses...).
  const REFUSALS = {
    torque_off: 'el par de los motores está desactivado. Actívalo (POST /robot/torque-on) antes de sembrar.',
    no_calibration: 'la cámara no está calibrada con el robot: añade al menos 4 puntos y ajusta la homografía.',
    busy: 'ya hay una siembra en curso. Párala antes de empezar otra.',
  };

  function refusalText(body, status) {
    if (REFUSALS[body.code]) return REFUSALS[body.code];
    if (body.code === 'missing_pose') return 'faltan poses enseñadas — ' + body.detail;
    if (body.code === 'unreachable') return 'hay alveolos fuera del alcance del brazo — ' + body.detail;
    return body.detail || 'el robot ha respondido HTTP ' + status + '.';
  }

  function startDemo(message) {
    run.mode = 'demo';
    run.detail = 'Sin robot: simulación en el navegador';
    setMode('MODO DEMO', true);
    toast(message);
    runDemo();
    renderRun();
  }

  async function startRun() {
    if (run) return;
    const queue = order();
    if (!queue.length) { toast('Asigna al menos una semilla a una casilla.'); return; }
    run = {
      queue,
      state: Object.fromEntries(queue.map(i => [i, 'pending'])),
      mode: 'robot',
      detail: 'Enviando el plan…',
      finished: false,
      ws: null,
      timer: null,
    };
    $('trayActions').hidden = true;
    $('runPanel').hidden = false;
    $('mapa-semillero').classList.add('running');
    document.body.classList.add('running');
    measureDock();
    setMode('Conectando…', false);
    renderRun();

    const plan = buildPlan(queue);
    if (!plan) {
      // No pixel centres: a real robot could not place anything. Only simulate when
      // there is no backend to talk to in the first place.
      let reachable = false;
      try { reachable = (await window.smartseedBackend.fetch('/robot/status', {}, 1500)).ok; } catch (e) { /* offline */ }
      if (reachable) {
        toast('Escanea el semillero con la cámara antes de sembrar: el robot necesita la posición de cada hueco.');
        closeRun();
        return;
      }
      startDemo('Sin robot ni escaneo: se muestra la siembra simulada.');
      return;
    }

    let res = null, offline = false;
    try {
      res = await window.smartseedBackend.fetch('/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(plan),
      }, 8000);
    } catch (e) { offline = true; }

    if (!run) return;  // stopped while the request was in flight
    if (offline) { startDemo('Sin backend del robot: se muestra la siembra simulada.'); return; }

    if (!res.ok) {
      let body = {};
      try { body = await res.json(); } catch (e) { /* no JSON body */ }
      toast('No se puede sembrar: ' + refusalText(body, res.status));
      closeRun();
      return;
    }

    run.mode = 'robot';
    run.detail = 'Plan enviado al robot';
    listenProgress();
    labelRobotMode();
    renderRun();
  }

  async function stopRun() {
    if (!run) return;
    if (run.finished) { closeRun(); return; }
    clearTimeout(run.timer);
    if (run.mode === 'robot') {
      try { await window.smartseedBackend.fetch('/stop', { method: 'POST' }); }
      catch (e) { /* the WebSocket close will report it */ }
    }
    finishRun('Siembra detenida.', 'Parada solicitada');
  }

  // ── Palette wiring ─────────────────────────────────────────────────────────

  const palette = $('seedGrid');
  palette.querySelectorAll('.seed').forEach(b => {
    const m = SEEDS[b.dataset.seed];
    if (!m) return;
    b.style.setProperty('--box', m.strong);
    b.style.setProperty('--box-tint', m.tint);
  });
  $('seedSidebar').appendChild(palette);
  const mobilePalette = palette.cloneNode(true);
  mobilePalette.removeAttribute('id');
  mobilePalette.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
  $('seedMobile').appendChild(mobilePalette);

  const isDesktop = () => !!(window.matchMedia && window.matchMedia('(min-width: 900px)').matches);

  document.querySelectorAll('.seed').forEach(b => {
    b.draggable = isDesktop();
    b.addEventListener('click', () => selectSeed(b.dataset.seed));
    b.addEventListener('dragstart', e => {
      selectSeed(b.dataset.seed);
      e.dataTransfer.setData('text/plain', b.dataset.seed);
      e.dataTransfer.effectAllowed = 'copy';
    });
  });

  const droppedSeed = e => {
    const raw = e.dataTransfer ? e.dataTransfer.getData('text/plain') : '';
    return SEEDS[raw] ? raw : selected;
  };

  document.querySelectorAll('[data-fill-all]').forEach(slot => {
    slot.setAttribute('aria-label', 'Rellenar todo el mapa con la variedad seleccionada');
    slot.addEventListener('click', () => fillAll(selected));
    slot.addEventListener('dragover', e => {
      e.preventDefault();
      slot.classList.add('drop-target');
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    });
    slot.addEventListener('dragleave', () => slot.classList.remove('drop-target'));
    slot.addEventListener('drop', e => {
      e.preventDefault();
      slot.classList.remove('drop-target');
      const key = droppedSeed(e);
      selectSeed(key);
      fillAll(key);
    });
  });

  // ── Tray wiring ────────────────────────────────────────────────────────────

  const grid = $('trayGrid');

  grid.addEventListener('click', e => {
    if (run) return;
    // A mobile drop already assigned this cell on pointerup; swallow the click after it.
    if (mobileDropAt && Date.now() - mobileDropAt < 700) { mobileDropAt = 0; e.preventDefault(); return; }
    const clear = e.target.closest('[data-clear-cell]');
    if (clear) { setCell(Number(clear.dataset.clearCell), null); return; }
    const cell = e.target.closest('[data-cell]');
    if (!cell) return;
    const i = Number(cell.dataset.cell);
    setCell(i, cells[i] === selected ? null : selected);
  });

  grid.addEventListener('dragover', e => {
    const cell = e.target.closest('[data-cell]');
    if (!cell || run) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    cell.classList.add('drop-target');
  });

  grid.addEventListener('dragleave', e => {
    const cell = e.target.closest('[data-cell]');
    if (cell && !cell.contains(e.relatedTarget)) cell.classList.remove('drop-target');
  });

  grid.addEventListener('drop', e => {
    const cell = e.target.closest('[data-cell]');
    if (!cell || run) return;
    e.preventDefault();
    cell.classList.remove('drop-target');
    setCell(Number(cell.dataset.cell), droppedSeed(e));
  });

  // On a phone, dragging a palette tile onto a cell ends as a pointerup over the cell.
  document.addEventListener('pointerup', e => {
    if (run || isDesktop() || !e.target.closest) return;
    const cell = e.target.closest('[data-cell]');
    if (!cell) return;
    setCell(Number(cell.dataset.cell), selected);
    mobileDropAt = Date.now();
  });

  $('clearTrayBtn').addEventListener('click', () => {
    if (run) return;
    cells = cells.map(() => null);
    saveLayout();
    cells.forEach((_, i) => paintCell(i));
    updateCounts();
    toast('Mapa vaciado.');
  });

  $('mapPlantBtn').addEventListener('click', startRun);
  $('stopRunBtn').addEventListener('click', stopRun);
  $('saveTemplateBtn').addEventListener('click', saveTemplate);
  $('deleteTemplateBtn').addEventListener('click', deleteTemplate);
  $('templateSelect').addEventListener('change', e => {
    if (run) { e.target.value = ''; return; }
    if (e.target.value) applyTemplate(e.target.value);
    else renderTemplates('');
  });

  // Manual fallback, only reachable when the browser has no live camera.
  $('createCustomTrayBtn').addEventListener('click', () => {
    if (window.smartseedScan && window.smartseedScan.cameraActive()) return;  // scanner.js owns the button then
    openApp($('customRows').value, $('customCols').value);
    toast('Mapa creado: ' + rows + ' × ' + cols + ' (' + total() + ' huecos).');
  });

  // ── Mobile dock height ─────────────────────────────────────────────────────
  // The dock is fixed over the page; --dock-h keeps the padding, the tray size and the
  // toast clear of it, whatever the palette ends up measuring.
  const dock = $('mobileSeedDock');
  const measureDock = () =>
    document.documentElement.style.setProperty('--dock-h', (dock.hidden ? 0 : dock.offsetHeight) + 'px');
  if (window.ResizeObserver) new ResizeObserver(measureDock).observe(dock);
  window.addEventListener('resize', measureDock);

  // ── Boot ───────────────────────────────────────────────────────────────────

  const saved = normalizeLayout(readJSON(LAYOUT_KEY, null) ?? readJSON(LEGACY_LAYOUT_KEY, null));
  if (saved && saved.rows && saved.cols) {
    rows = saved.rows;
    cols = saved.cols;
    cells = Array.from({ length: rows * cols }, (_, i) => saved.cells[i] || null);
  } else if (saved) {
    cells = Array.from({ length: total() }, (_, i) => saved.cells[i] || null);
  } else {
    cells = Array(total()).fill(null);
  }
  $('customRows').value = rows;
  $('customCols').value = cols;

  renderBoxLegend();
  selectSeed(selected);
  renderTemplates('');
  renderTray();

  window.smartseedApp = {
    openApp,
    resizeTray: (r, c) => { if (!run && (r !== rows || c !== cols)) setSize(r, c); },
    dims: () => ({ rows, cols }),
    isRunning: () => !!run,
    seedCount: filledCount,
  };
})();
