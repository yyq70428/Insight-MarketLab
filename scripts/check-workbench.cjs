const { chromium } = require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  if (process.argv.includes('--batch')) throw new Error('區間回測請使用 scripts/check-flow.cjs；此腳本僅檢查版面，不建立工作。');
  const output = path.resolve('artifacts/workbench-check');
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 800 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto((process.env.MARKETLAB_TEST_URL || 'http://127.0.0.1:9021') + '/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('#dataStatus').textContent.includes('1214') || document.querySelector('#dataStatus').textContent.includes('已連線'), null, { timeout: 60000 });
    const dimensions = [];
    for (const [width, height] of [[2048, 1006], [1536, 800], [1366, 768], [1280, 720]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(750);
      dimensions.push(await page.evaluate(() => {
        const rect = selector => {
          const r = document.querySelector(selector).getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height, bottom: r.bottom, right: r.right };
        };
        return { viewport: [innerWidth, innerHeight], document: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
          sidebar: rect('.agent-sidebar'), chart: rect('.chart-column'), footer: rect('.chart-footer'), toolbar: rect('.topbar'),
          toolbarOverflow: document.querySelector('.topbar').scrollWidth > innerWidth,
          overflowingControls: [...document.querySelectorAll('.agent-sidebar input, .agent-sidebar select, .agent-sidebar button')]
            .filter(node => { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.right > innerWidth + 1 || r.left < document.querySelector('.agent-sidebar').getBoundingClientRect().left); })
            .map(node => node.id || node.tagName)
        };
      }));
      await page.screenshot({ path: path.join(output, `after-${width}.png`) });
    }
    {
      await page.locator('[data-toggle="zones"]').click();
      await page.waitForTimeout(250);
      await page.screenshot({ path: path.join(output, 'zones-off.png') });
      await page.locator('[data-toggle="zones"]').click();
      await page.waitForTimeout(250);
    }
    const checks = { dimensions, errors };
    await fs.writeFile(path.join(output, 'after-layout.json'), JSON.stringify(checks, null, 2));
    console.log(JSON.stringify(checks, null, 2));
    if (errors.length || dimensions.some(item => item.document[0] > item.viewport[0] || item.document[1] > item.viewport[1] + 1 || item.toolbarOverflow || item.overflowingControls.length)) {
      throw new Error('Workbench layout or browser runtime check failed');
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
