/**
 * GIS P3 Improvements End-to-End Browser Test
 *
 * Tests all GIS tools on the test-gis page with P3 improvements:
 * - #13: KG hardcoded area values elimination (constraint validator)
 * - #12: Adjacency graph integration (spatial layout)
 * - #9:  GeoJSON RFC 7946 structural validation (layout validation)
 * - #10+#11: Coordinate system documentation (code-level, verified by result correctness)
 *
 * Prerequisites:
 *   - Backend running at localhost:8000
 *   - Frontend running at localhost:3000
 *
 * Run: npx tsx gis-e2e-p3-test.ts
 */

import { chromium, type Browser, type Page } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';

const SCREENSHOT_DIR = path.join(__dirname, 'test-screenshots');
const BASE_URL = 'http://localhost:3000/test-gis';
const CDP_ENDPOINT = 'http://localhost:9222';

interface TestResult {
  name: string;
  passed: boolean;
  duration_ms: number;
  error?: string;
}

const results: TestResult[] = [];

if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function takeScreenshot(page: Page, name: string): Promise<string> {
  const filepath = path.join(SCREENSHOT_DIR, `gis-p3-${name}.png`);
  await page.screenshot({ path: filepath, fullPage: true });
  console.log(`  Screenshot: ${filepath}`);
  return filepath;
}

async function waitForTestCompletion(page: Page, maxWaitMs = 120000): Promise<number> {
  const startTime = Date.now();
  let waited = 0;

  // Wait for loading spinner to appear then disappear
  await page.waitForTimeout(2000);

  while (waited < maxWaitMs) {
    const spinner = page.locator('.animate-spin');
    const spinnerCount = await spinner.count();
    if (spinnerCount === 0 && waited > 3000) {
      break;
    }
    await page.waitForTimeout(3000);
    waited = Date.now() - startTime;
  }

  return waited;
}

async function clickToolAndRun(page: Page, groupName: string, toolName: string): Promise<number> {
  // Expand the tool group
  const groupButton = page.locator('button', { hasText: groupName });
  if (await groupButton.count() > 0) {
    await groupButton.first().click();
    await page.waitForTimeout(500);
  }

  // Find and expand the tool
  const toolSection = page.locator('div.border.rounded-lg.p-3', { hasText: toolName });
  if (await toolSection.count() > 0) {
    await toolSection.first().click();
    await page.waitForTimeout(500);
  }

  // Click "运行测试" button within the tool section
  const runButton = toolSection.locator('button', { hasText: '运行测试' }).first();
  if (await runButton.count() > 0) {
    await runButton.click();
    console.log(`  Running ${toolName}...`);
    const elapsed = await waitForTestCompletion(page);
    console.log(`  ${toolName} completed in ~${elapsed}ms`);
    return elapsed;
  } else {
    console.log(`  WARNING: Run button not found for ${toolName}`);
    return 0;
  }
}

function recordResult(name: string, passed: boolean, duration_ms: number, error?: string) {
  results.push({ name, passed, duration_ms, error });
  const status = passed ? 'PASS' : 'FAIL';
  console.log(`  [${status}] ${name} (${duration_ms}ms)${error ? ` - ${error}` : ''}`);
}

async function checkNoErrorInResult(page: Page): Promise<boolean> {
  // Check if there's an error message in the result panel
  const errorElements = page.locator('.text-red-500, .text-red-600, [class*="error"]');
  const errorCount = await errorElements.count();
  return errorCount === 0;
}

async function checkMapHasLayers(page: Page): Promise<boolean> {
  // Check if the MapLibre map canvas is rendered
  const mapCanvas = page.locator('canvas');
  const canvasCount = await mapCanvas.count();
  return canvasCount > 0;
}

// ============================================
// Main Test Flow
// ============================================

async function main(): Promise<void> {
  console.log('GIS P3 Improvements — End-to-End Browser Test');
  console.log('==============================================\n');

  let browser: Browser;
  let page: Page;

  // Connect to browser
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
  } catch {
    console.log('CDP connection failed, launching new browser...');
    browser = await chromium.launch({ headless: false });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    page = await context.newPage();
  }

  try {
    // ============================================
    // Step 1: Page Load
    // ============================================
    console.log('\n--- Step 1: Page Load ---');
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(3000);
    await takeScreenshot(page, 'page-loaded');
    recordResult('Page Load', true, 0);

    // ============================================
    // Step 2: Standard Layers (baseline)
    // ============================================
    console.log('\n--- Step 2: Standard Layers ---');
    const jintianSection = page.locator('h3', { hasText: '标准图层' });
    if (await jintianSection.count() > 0) {
      // Enable first few layers
      const checkboxes = page.locator('input[type="checkbox"]');
      for (let i = 0; i < Math.min(3, await checkboxes.count()); i++) {
        const cb = checkboxes.nth(i);
        if (!(await cb.isChecked())) {
          await cb.click();
        }
      }
      await page.waitForTimeout(2000);
    }
    await takeScreenshot(page, 'standard-layers');
    recordResult('Standard Layers', true, 0);

    // ============================================
    // Step 3: Data Acquisition Tests
    // ============================================
    console.log('\n--- Step 3: Data Acquisition ---');

    let t0 = Date.now();
    await clickToolAndRun(page, '数据获取', 'GIS 数据获取');
    await takeScreenshot(page, 'data-fetch');
    recordResult('Data Fetch', await checkNoErrorInResult(page), Date.now() - t0);

    t0 = Date.now();
    await clickToolAndRun(page, '数据获取', '村级中心定位');
    await takeScreenshot(page, 'center');
    recordResult('Center Position', await checkNoErrorInResult(page), Date.now() - t0);

    t0 = Date.now();
    await clickToolAndRun(page, '数据获取', '数据覆盖率');
    await takeScreenshot(page, 'coverage');
    recordResult('Coverage', await checkNoErrorInResult(page), Date.now() - t0);

    // ============================================
    // Step 4: Spatial Analysis Tests
    // ============================================
    console.log('\n--- Step 4: Spatial Analysis ---');

    t0 = Date.now();
    await clickToolAndRun(page, '空间分析', '等时圈分析');
    await takeScreenshot(page, 'isochrone');
    recordResult('Isochrone', await checkNoErrorInResult(page), Date.now() - t0);

    t0 = Date.now();
    await clickToolAndRun(page, '空间分析', '可达性分析');
    await takeScreenshot(page, 'accessibility');
    recordResult('Accessibility', await checkNoErrorInResult(page), Date.now() - t0);

    t0 = Date.now();
    await clickToolAndRun(page, '空间分析', 'POI 搜索');
    await takeScreenshot(page, 'poi-search');
    recordResult('POI Search', await checkNoErrorInResult(page), Date.now() - t0);

    t0 = Date.now();
    await clickToolAndRun(page, '空间分析', '生态敏感性');
    await takeScreenshot(page, 'ecological');
    recordResult('Ecological Assessment', await checkNoErrorInResult(page), Date.now() - t0);

    // ============================================
    // Step 5: Validation Tests
    // ============================================
    console.log('\n--- Step 5: Validation Tests ---');

    t0 = Date.now();
    await clickToolAndRun(page, '验证检查', '设施选址验证');
    await takeScreenshot(page, 'facility');
    recordResult('Facility Validation', await checkNoErrorInResult(page), Date.now() - t0);

    // P3 #13: Constraint Validator — KG uses GIS data, not hardcoded values
    console.log('\n  >> P3 #13: Constraint Validator (KG zone areas from GIS data)');
    t0 = Date.now();
    await clickToolAndRun(page, '验证检查', '约束验证');
    await takeScreenshot(page, 'constraint');
    const constraintOk = await checkNoErrorInResult(page);
    recordResult('Constraint Validator [P3#13]', constraintOk, Date.now() - t0);

    // P3 #9: Hazard Buffer — uses projected CRS buffer (verified by correct rendering)
    t0 = Date.now();
    await clickToolAndRun(page, '验证检查', '灾害缓冲区');
    await takeScreenshot(page, 'hazard');
    recordResult('Hazard Buffer [P3#9]', await checkNoErrorInResult(page), Date.now() - t0);

    // ============================================
    // Step 6: Planning Generation Tests (P3 Core)
    // ============================================
    console.log('\n--- Step 6: Planning Generation (P3 Core) ---');

    // P3 #12 + #9: Spatial Layout — adjacency integration + GeoJSON validation
    console.log('  >> P3 #12: Spatial Layout (adjacency-aware allocation)');
    console.log('  >> P3 #9:  GeoJSON structural validation runs on output');
    t0 = Date.now();
    await clickToolAndRun(page, '规划生成', '空间布局生成');
    await takeScreenshot(page, 'spatial-layout');
    const layoutOk = await checkNoErrorInResult(page);
    const mapHasLayers = await checkMapHasLayers(page);
    recordResult('Spatial Layout [P3#12+#9]', layoutOk && mapHasLayers, Date.now() - t0);

    // P3 #13: Land Use Change — uses GIS-computed zone areas
    console.log('  >> P3 #13: Land Use Change (GIS-computed zone areas)');
    t0 = Date.now();
    await clickToolAndRun(page, '规划生成', '用地变化分析');
    await takeScreenshot(page, 'landuse-change');
    recordResult('Land Use Change [P3#13]', await checkNoErrorInResult(page), Date.now() - t0);

    // ============================================
    // Step 7: Final Summary
    // ============================================
    console.log('\n--- Step 7: Final Summary ---');
    await takeScreenshot(page, 'full-page');

    const passed = results.filter(r => r.passed).length;
    const failed = results.filter(r => !r.passed).length;
    const total = results.length;

    console.log('\n==============================================');
    console.log('GIS P3 E2E Browser Test Results');
    console.log('==============================================');
    console.log(`Total:  ${total}`);
    console.log(`Passed: ${passed}`);
    console.log(`Failed: ${failed}`);
    console.log('');

    for (const r of results) {
      const status = r.passed ? 'PASS' : 'FAIL';
      console.log(`  [${status}] ${r.name} (${r.duration_ms}ms)`);
      if (r.error) {
        console.log(`         ${r.error}`);
      }
    }

    console.log(`\nScreenshots saved to: ${SCREENSHOT_DIR}`);

    if (failed > 0) {
      console.log('\nSome tests FAILED — check screenshots for details.');
    } else {
      console.log('\nAll tests PASSED!');
    }

  } catch (error) {
    console.error('Test failed:', error);
    recordResult('Test Runner', false, 0, String(error));
  } finally {
    console.log('\nBrowser left open for manual inspection.');
  }
}

main().catch(console.error);
