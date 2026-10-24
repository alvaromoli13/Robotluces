// Camera flow in a real browser, with Chromium's synthetic webcam. Covers the parts
// jsdom cannot reach: entering the map-over-camera mode, keeping the layout through a
// scan, and reopening the scanner from inside the app.
//
//   npm install                                  # once, in tests/web/
//   CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run camera
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots');
const PAGE = 'file://' + path.resolve(__dirname, '../../web/index.html');

const out = [];
const ok = (name, cond, extra) => out.push((cond ? 'PASS' : 'FAIL') + ' ' + name + (!cond && extra !== undefined ? ' :: ' + extra : ''));
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: [
      '--no-sandbox', '--disable-gpu', '--allow-file-access-from-files', '--no-first-run',
      '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    ],
    userDataDir: path.join(OUT, '.profile-camera'),
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/ERR_CONNECTION_REFUSED/.test(m.text())) errors.push(m.text()); });

  // A layout saved by a previous session: scanning must not throw it away.
  await page.goto(PAGE, { waitUntil: 'load' });
  await page.evaluate(() => {
    localStorage.clear();
    localStorage.setItem('smartseed.lastLayout', JSON.stringify({
      rows: 3, cols: 3, cells: ['TOMATE', null, 'LIMON', null, 'PIMIENTO', null, null, null, 'BERENJENAS'],
    }));
  });
  await page.reload({ waitUntil: 'load' });

  ok('saved layout is restored before scanning', await page.evaluate(() =>
    document.querySelectorAll('#trayGrid .tray-cell.filled').length === 4));

  await page.click('#startScanBtn');
  await page.waitForFunction(() => document.getElementById('cameraPreview').videoWidth > 0, { timeout: 15000 });
  await sleep(600);

  const scanned = await page.evaluate(() => {
    const panel = document.getElementById('mapa-semillero');
    const stage = panel.querySelector('.scan-stage');
    const cell = document.querySelector('#trayGrid [data-cell="0"]');
    return {
      appVisible: !document.getElementById('mainApp').hidden && document.getElementById('scannerGate').hidden,
      cameraMode: panel.classList.contains('camera-mode'),
      panelMoved: panel.contains(document.getElementById('cameraPanel')),
      gridOverVideo: stage.contains(document.getElementById('trayGrid')),
      sizeFieldsMoved: document.getElementById('cameraPanel').contains(document.getElementById('customRows')),
      reopenHidden: document.getElementById('reopenCameraBtn').hidden,
      filled: document.querySelectorAll('#trayGrid .tray-cell.filled').length,
      cellPositioned: cell.style.left !== '' && cell.style.width !== '',
      status: document.getElementById('scanStatus').textContent,
      arucoLoaded: !!window.AR,
    };
  });
  await page.screenshot({ path: `${OUT}/camera-1-map-over-video.png` });

  ok('the app is open behind the camera', scanned.appVisible);
  ok('map-over-camera mode is on', scanned.cameraMode);
  ok('the camera panel moved into the map', scanned.panelMoved);
  ok('the tray grid is painted over the video', scanned.gridOverVideo);
  ok('the size fields moved next to the video', scanned.sizeFieldsMoved);
  ok('the scan button is hidden while scanning', scanned.reopenHidden);
  ok('scanning keeps the saved layout', scanned.filled === 4, scanned.filled);
  ok('cells are positioned over the frame', scanned.cellPositioned);
  ok('js-aruco2 is available, so the status counts markers', scanned.arucoLoaded &&
    /Marcadores detectados/.test(scanned.status), scanned.status);

  // Typing a size switches back to the grid and resizes the tray live.
  await page.evaluate(() => {
    const f = document.getElementById('customRows');
    f.value = '4';
    f.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(200);
  ok('typing rows resizes the tray', await page.evaluate(() =>
    document.querySelectorAll('#trayGrid [data-cell]').length === 12),
    await page.evaluate(() => document.querySelectorAll('#trayGrid [data-cell]').length));
  ok('resizing keeps the seeds that still fit', await page.evaluate(() =>
    document.querySelectorAll('#trayGrid .tray-cell.filled').length === 4));

  await page.click('#closeCameraBtn');
  await sleep(300);
  const closed = await page.evaluate(() => ({
    cameraMode: document.getElementById('mapa-semillero').classList.contains('camera-mode'),
    gridBack: document.getElementById('mapa-semillero').contains(document.getElementById('trayGrid')) &&
      !document.querySelector('.scan-stage').contains(document.getElementById('trayGrid')),
    panelHidden: document.getElementById('cameraPanel').hidden,
    reopenVisible: !document.getElementById('reopenCameraBtn').hidden,
    cellInline: document.querySelector('#trayGrid [data-cell="0"]').style.left,
    lastLayout: window.smartseedScan.lastLayout,
    filled: document.querySelectorAll('#trayGrid .tray-cell.filled').length,
  }));
  await page.screenshot({ path: `${OUT}/camera-2-closed.png` });

  ok('closing the camera leaves map mode', !closed.cameraMode);
  ok('the tray grid goes back to the panel', closed.gridBack);
  ok('the camera panel is hidden again', closed.panelHidden);
  ok('the scan button comes back', closed.reopenVisible);
  ok('the absolute positions are cleared', closed.cellInline === '');
  ok('the layout survives closing the camera', closed.filled === 4, closed.filled);
  ok('the last scan is kept for the robot plan',
    closed.lastLayout && closed.lastLayout.cells.length === 12 &&
    closed.lastLayout.imageSize[0] > 0 && closed.lastLayout.cells[0].x >= 0,
    JSON.stringify(closed.lastLayout && { n: closed.lastLayout.cells.length, size: closed.lastLayout.imageSize }));

  // The regression this test exists for: the scanner used to be unreachable after this.
  await page.click('#reopenCameraBtn');
  await page.waitForFunction(() => document.getElementById('cameraPreview').videoWidth > 0, { timeout: 15000 });
  await sleep(400);
  const reopened = await page.evaluate(() => ({
    cameraMode: document.getElementById('mapa-semillero').classList.contains('camera-mode'),
    gridOverVideo: document.querySelector('.scan-stage').contains(document.getElementById('trayGrid')),
    filled: document.querySelectorAll('#trayGrid .tray-cell.filled').length,
  }));
  ok('the camera can be reopened from the map', reopened.cameraMode && reopened.gridOverVideo);
  ok('reopening keeps the layout', reopened.filled === 4, reopened.filled);

  ok('no page errors', errors.length === 0, JSON.stringify(errors));

  await browser.close();
  console.log(out.join('\n'));
  const fails = out.filter(l => l.startsWith('FAIL'));
  console.log('\n' + (out.length - fails.length) + '/' + out.length + ' passed');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('CAMERA TEST FAILED:', e.stack || e.message); process.exit(1); });
