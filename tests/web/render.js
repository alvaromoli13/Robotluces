const fs = require('fs');
// Real-browser render check: opens every screen at desktop and phone sizes, saves a
// screenshot of each, and reports console errors, failed requests and layout overflow.
//
//   npm install                                  # once, in tests/web/
//   CHROME_PATH="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" npm run render
//
// A failed request to localhost:8000 is expected: there is no robot backend in the test.
const path = require('path');
const puppeteer = require('puppeteer-core');

// Any Chromium works; point CHROME_PATH at the one installed on this machine.
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const OUT = process.env.OUT_DIR || path.resolve(__dirname, 'shots');
const PAGE = 'file://' + path.resolve(__dirname, '../../web/index.html');

const VIEWPORTS = {
  desktop: { width: 1440, height: 900, deviceScaleFactor: 1 },
  phone: { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--allow-file-access-from-files', '--no-first-run'],
    userDataDir: path.join(OUT, '.profile'),
  });

  fs.mkdirSync(OUT, { recursive: true });
  const report = [];

  for (const [name, viewport] of Object.entries(VIEWPORTS)) {
    const page = await browser.newPage();
    await page.setViewport(viewport);
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    page.on('requestfailed', r => errors.push('requestfailed: ' + r.url().split('/').pop() + ' ' + r.failure().errorText));

    // Each viewport starts from a clean slate; a layout left over from the previous run
    // would be restored from localStorage and change what the clicks do.
    await page.goto(PAGE, { waitUntil: 'load' });
    await page.evaluate(() => localStorage.clear());
    await page.reload({ waitUntil: 'load' });
    await page.screenshot({ path: `${OUT}/${name}-1-gate.png` });

    // Fonts must come from web/fonts, never from the network.
    const fonts = await page.evaluate(async () => {
      await document.fonts.ready;
      return [...document.fonts].map(f => f.family + ' ' + f.status);
    });

    // Open the app with a 5x8 tray and a mixed layout.
    const filledAfterEdit = await page.evaluate(() => {
      window.smartseedApp.openApp(5, 8);
      const seeds = [...document.querySelectorAll('#seedSidebar .seed')];
      [0, 1, 2, 8, 9, 17, 18, 19, 20, 26, 27, 34, 35, 36, 37].forEach((i, k) => {
        seeds[k % 4].click();
        document.querySelector('#trayGrid [data-cell="' + i + '"]').click();
      });
      return document.querySelectorAll('.tray-cell.filled').length;
    });
    await new Promise(r => setTimeout(r, 250));
    await page.screenshot({ path: `${OUT}/${name}-2-map.png` });

    const metrics = await page.evaluate(() => {
      const grid = document.getElementById('trayGrid');
      const cell = grid.querySelector('[data-cell]');
      const r = cell.getBoundingClientRect();
      const g = grid.getBoundingClientRect();
      return {
        bodyScrollW: document.documentElement.scrollWidth,
        viewportW: window.innerWidth,
        gridBottom: Math.round(g.bottom),
        viewportH: window.innerHeight,
        cell: Math.round(r.width) + 'x' + Math.round(r.height),
        cellSquare: Math.abs(r.width - r.height) < 1.5,
        cellsVisible: [...grid.querySelectorAll('[data-cell]')].filter(c => {
          const b = c.getBoundingClientRect();
          return b.width > 0 && b.height > 0;
        }).length,
        gridOverflows: grid.scrollWidth > grid.clientWidth + 1,
        legendPills: document.querySelectorAll('#boxLegend li').length,
        paletteVisible: !!document.querySelector('#seedSidebar .seed') &&
          getComputedStyle(document.querySelector('.sidebar')).display !== 'none',
        dockVisible: getComputedStyle(document.getElementById('mobileSeedDock')).display !== 'none',
      };
    });

    // The seed modal, empty and filled in, then a custom seed planted on the map.
    const palette = name === 'desktop' ? '#seedSidebar' : '#seedMobile';
    await page.click(palette + ' [data-add-seed]');
    await new Promise(r => setTimeout(r, 150));
    await page.screenshot({ path: `${OUT}/${name}-4-modal.png` });
    await page.type('#seedName', 'Albahaca');
    await page.click('#seedEmojiGrid [data-emoji="🌿"]');
    await page.click('#seedColorGrid [data-color="blue"]');
    const modalMetrics = await page.evaluate(() => {
      const card = document.querySelector('.modal-card').getBoundingClientRect();
      return {
        cardInsideViewport: card.left >= 0 && card.right <= window.innerWidth && card.top >= 0 && card.bottom <= window.innerHeight,
        cardW: Math.round(card.width), cardH: Math.round(card.height),
        pageOverflowX: document.documentElement.scrollWidth > window.innerWidth,
        modalScrollsX: document.querySelector('.modal-card').scrollWidth > document.querySelector('.modal-card').clientWidth + 1,
        focusInside: document.querySelector('.modal-card').contains(document.activeElement),
      };
    });
    await page.screenshot({ path: `${OUT}/${name}-5-modal-filled.png` });
    await page.click('#seedSave');
    await new Promise(r => setTimeout(r, 150));
    await page.evaluate(() => [3, 4, 10, 11, 12, 25, 28, 29].forEach(i => document.querySelector('#trayGrid [data-cell="' + i + '"]').click()));
    await new Promise(r => setTimeout(r, 200));
    const paletteMetrics = await page.evaluate(() => {
      const tiles = [...document.querySelectorAll((window.innerWidth >= 900 ? '#seedSidebar' : '#seedMobile') + ' .seed-item')];
      const tops = new Set(tiles.map(t => Math.round(t.getBoundingClientRect().top)));
      return { tiles: tiles.length, rowsOfTiles: tops.size, modalClosed: document.getElementById('seedModal').hidden,
        pageOverflowX: document.documentElement.scrollWidth > window.innerWidth,
        customCells: document.querySelectorAll('#trayGrid .tray-cell.filled[aria-label*="Albahaca"]').length };
    });
    await page.screenshot({ path: `${OUT}/${name}-6-custom-map.png` });

    // Planting run (no backend -> demo simulation).
    await page.evaluate(() => document.getElementById('mapPlantBtn').click());
    await new Promise(r => setTimeout(r, 3200));
    await page.screenshot({ path: `${OUT}/${name}-3-run.png` });
    const runState = await page.evaluate(() => ({
      mode: document.getElementById('runMode').textContent,
      planting: document.querySelectorAll('.tray-cell.planting').length,
      done: document.querySelectorAll('.tray-cell.done').length,
      count: document.getElementById('runCount').textContent,
      panelVisible: !document.getElementById('runPanel').hidden,
    }));

    report.push({ name, viewport: viewport.width + 'x' + viewport.height, fonts, filledAfterEdit, metrics, modalMetrics, paletteMetrics, runState, errors });
    await page.close();
  }

  await browser.close();
  console.log(JSON.stringify(report, null, 2));
})().catch(e => { console.error('SHOTS FAILED:', e.message); process.exit(1); });
