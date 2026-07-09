/**
 * GIS End-to-End Browser Test Script
 *
 * Uses Playwright to test the test-gis page:
 * 1. Check page load and service status
 * 2. Test standard layers
 * 3. Run all 13 GIS tool tests
 * 4. Capture screenshots and analyze results
 *
 * Run: npx tsx gis-e2e-test.ts
 */

import { chromium, type Browser, type Page } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';

const SCREENSHOT_DIR = path.join(__dirname, 'test-screenshots');
const BASE_URL = 'http://localhost:3000/test-gis';
const CDP_ENDPOINT = 'http://localhost:9222';

// Ensure screenshot directory exists
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function takeScreenshot(page: Page, name: string): Promise<string> {
  const filepath = path.join(SCREENSHOT_DIR, `${name}.png`);
  await page.screenshot({ path: filepath, fullPage: true });
  console.log(`📸 Screenshot saved: ${filepath}`);
  return filepath;
}

async function screenshotAndAnalyze(page: Page, name: string): Promise<void> {
  const filepath = await takeScreenshot(page, name);
  // Read the screenshot file size for verification
  const stats = fs.statSync(filepath);
  console.log(`  File size: ${stats.size} bytes`);
}

async function clickToolAndRun(page: Page, groupName: string, toolName: string): Promise<void> {
  // Expand the tool group
  const groupButton = page.locator('button', { hasText: groupName });
  await groupButton.click();
  await page.waitForTimeout(500);

  // Expand the tool
  const toolButton = page.locator('div.border.rounded-lg.p-3 button', { hasText: toolName });
  await toolButton.first().click();
  await page.waitForTimeout(500);

  // Click "运行测试" button
  const runButton = page.locator('button', { hasText: '运行测试' }).first();
  await runButton.click();

  // Wait for test to complete (up to 60 seconds)
  console.log(`  Running ${toolName}...`);
  await page.waitForTimeout(5000);

  // Check for loading spinner - wait until it disappears
  const spinner = page.locator('.animate-spin');
  let maxWait = 120000;
  let waited = 5000;
  while (await spinner.count() > 0 && waited < maxWait) {
    await page.waitForTimeout(3000);
    waited += 3000;
    console.log(`  Still running... (${waited}ms)`);
  }

  console.log(`  ${toolName} completed after ~${waited}ms`);
}

async function main(): Promise<void> {
  console.log('🚀 GIS End-to-End Browser Test Starting...');

  let browser: Browser;
  let page: Page;

  // Try connecting to existing Chrome via CDP
  try {
    console.log(`Connecting to Chrome via CDP at ${CDP_ENDPOINT}...`);
    browser = await chromium.connectOverCDP(CDP_ENDPOINT);
    const contexts = browser.contexts();
    if (contexts.length > 0) {
      page = contexts[0].pages()[0] || await contexts[0].newPage();
    } else {
      const context = await browser.newContext();
      page = await context.newPage();
    }
  } catch (e) {
    console.log('CDP connection failed, launching new browser...');
    browser = await chromium.launch({ headless: false });
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    page = await context.newPage();
  }

  try {
    // ============================================
    // Step 1: Page Load & Service Status
    // ============================================
    console.log('\n=== Step 1: Page Load & Service Status ===');
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(3000);

    const title = await page.title();
    console.log(`Page title: ${title}`);

    // Check page content
    const pageContent = await page.content();
    const hasHeader = pageContent.includes('GIS');
    console.log(`Header found: ${hasHeader}`);

    // Check service status indicator
    const statusDot = page.locator('.rounded-full').first();
    const statusClass = await statusDot.evaluate(el => el.className);
    console.log(`Status dot class: ${statusClass}`);

    await screenshotAndAnalyze(page, 'gis-page-loaded');

    // ============================================
    // Step 2: Standard Layers
    // ============================================
    console.log('\n=== Step 2: Standard Layers ===');

    // Check if jintian files loaded
    const jintianSection = page.locator('h3', { hasText: '标准图层' });
    if (await jintianSection.count() > 0) {
      console.log('标准图层面板 found');

      // Check layer checkboxes
      const checkboxes = page.locator('input[type="checkbox"]');
      const checkboxCount = await checkboxes.count();
      console.log(`Found ${checkboxCount} layer checkboxes`);

      // Toggle a few status layer checkboxes
      const labels = page.locator('label');
      const labelCount = await labels.count();
      console.log(`Found ${labelCount} layer labels`);

      // Click first few checkboxes to enable layers
      for (let i = 0; i < Math.min(3, checkboxCount); i++) {
        const cb = checkboxes.nth(i);
        const isChecked = await cb.isChecked();
        if (!isChecked) {
          await cb.click();
          console.log(`  Enabled layer checkbox ${i}`);
        }
      }

      await page.waitForTimeout(2000);
      await screenshotAndAnalyze(page, 'gis-standard-layers');
    } else {
      console.log('标准图层面板 not found (may need backend data)');
    }

    // ============================================
    // Step 3: Data Fetch Tests
    // ============================================
    console.log('\n=== Step 3: Data Fetch Tests ===');

    // 3a: data-fetch
    await clickToolAndRun(page, '数据获取', 'GIS 数据获取');
    await screenshotAndAnalyze(page, 'gis-data-fetch');

    // 3b: center
    await clickToolAndRun(page, '数据获取', '村级中心定位');
    await screenshotAndAnalyze(page, 'gis-center');

    // 3c: coverage
    await clickToolAndRun(page, '数据获取', '数据覆盖率');
    await screenshotAndAnalyze(page, 'gis-coverage');

    // ============================================
    // Step 4: Spatial Analysis Tests
    // ============================================
    console.log('\n=== Step 4: Spatial Analysis Tests ===');

    // 4a: isochrone
    await clickToolAndRun(page, '空间分析', '等时圈分析');
    await screenshotAndAnalyze(page, 'gis-isochrone');

    // 4b: accessibility
    await clickToolAndRun(page, '空间分析', '可达性分析');
    await screenshotAndAnalyze(page, 'gis-accessibility');

    // 4c: poi-search
    await clickToolAndRun(page, '空间分析', 'POI 搜索');
    await screenshotAndAnalyze(page, 'gis-poi-search');

    // 4d: ecological
    await clickToolAndRun(page, '空间分析', '生态敏感性');
    await screenshotAndAnalyze(page, 'gis-ecological');

    // ============================================
    // Step 5: Validation Tests
    // ============================================
    console.log('\n=== Step 5: Validation Tests ===');

    // 5a: facility-validation
    await clickToolAndRun(page, '验证检查', '设施选址验证');
    await screenshotAndAnalyze(page, 'gis-facility');

    // 5b: constraint-validator
    await clickToolAndRun(page, '验证检查', '约束验证');
    await screenshotAndAnalyze(page, 'gis-constraint');

    // 5c: hazard-buffer
    await clickToolAndRun(page, '验证检查', '灾害缓冲区');
    await screenshotAndAnalyze(page, 'gis-hazard');

    // ============================================
    // Step 6: Planning Generation Tests
    // ============================================
    console.log('\n=== Step 6: Planning Generation Tests ===');

    // 6a: spatial-layout (most important test)
    await clickToolAndRun(page, '规划生成', '空间布局生成');
    await screenshotAndAnalyze(page, 'gis-spatial-layout');

    // 6b: landuse-change
    await clickToolAndRun(page, '规划生成', '用地变化分析');
    await screenshotAndAnalyze(page, 'gis-landuse-change');

    // ============================================
    // Step 7: Final Summary
    // ============================================
    console.log('\n=== Step 7: Final Summary ===');
    await screenshotAndAnalyze(page, 'gis-full-page');

    // Check test results count
    const resultItems = page.locator('.text-sm.p-2.rounded');
    const resultCount = await resultItems.count();
    console.log(`\nTotal test results displayed: ${resultCount}`);

    // Check map layers
    const layerInfo = page.locator('.bg-gray-100.px-1.rounded.text-xs');
    const layerCount = await layerInfo.count();
    console.log(`Map layers shown: ${layerCount}`);

    console.log('\n✅ GIS E2E Browser Test Complete!');
    console.log(`Screenshots saved to: ${SCREENSHOT_DIR}`);

  } catch (error) {
    console.error('❌ Test failed:', error);
  } finally {
    // Don't close the browser - let user inspect results
    console.log('\nBrowser left open for manual inspection.');
  }
}

main().catch(console.error);
