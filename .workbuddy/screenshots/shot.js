const { chromium } = require('playwright');
const path = require('path');

const pages = [
  { name: 'kg_3d', file: 'F:/project/Village_Planning_Agent/output/kg_inspection/kg_inspection_v2.html' },
  { name: 'kg_2d', file: 'F:/project/Village_Planning_Agent/output/kg_inspection/kg_inspection_v2.html', mode: '2d' },
  { name: 'overview', file: 'F:/project/Village_Planning_Agent/output/design_preview/planning_overview.html' },
  { name: 'document', file: 'F:/project/Village_Planning_Agent/output/design_preview/planning_document.html' },
];

const outDir = 'F:/project/Village_Planning_Agent/.workbuddy/screenshots';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });

  for (const p of pages) {
    const page = await context.newPage();
    await page.goto('file:///' + p.file.replace(/\\/g, '/'));
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(p.mode === '2d' ? 3000 : 2500);

    if (p.mode === '2d') {
      // click 平面 button
      const btn = page.locator('#viewSeg .seg-btn[data-mode="2d"]');
      if (await btn.count()) await btn.click();
      await page.waitForTimeout(1200);
    }

    await page.screenshot({ path: path.join(outDir, `${p.name}.png`), fullPage: false });
    console.log('screenshot:', p.name);
    await page.close();
  }

  await browser.close();
})();
