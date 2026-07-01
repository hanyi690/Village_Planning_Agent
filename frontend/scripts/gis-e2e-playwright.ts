/**
 * GIS 全工具 Playwright 端对端测试
 *
 * 测试 test-gis 页面全部 13 个 GIS 工具：
 *   1. 导航到页面，验证页面加载
 *   2. 逐个展开工具组 → 点击工具 → 运行测试 → 验证结果
 *   3. 每个工具截图
 *   4. 验证地图 canvas 渲染
 *   5. 生成测试报告
 *
 * 运行前提：
 *   - 后端运行在 http://localhost:8000
 *   - 前端运行在 http://localhost:3000
 *   - npx playwright install chromium
 *
 * 运行：npx tsx scripts/gis-e2e-playwright.ts
 */

import { chromium, type Browser, type Page } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000/test-gis';
const SCREENSHOT_DIR = path.join(__dirname, '..', '..', 'docs', 'test-reports');
const TOOL_TIMEOUT_MS = 120_000;

// ============================================
// Tool definitions matching ToolTestPanel.tsx
// ============================================

interface ToolDef {
  id: string;
  name: string;
  group: string;
  p3Tag?: string;
}

const TOOLS: ToolDef[] = [
  // 数据获取
  { id: 'data-fetch', name: 'GIS 数据获取', group: '数据获取' },
  { id: 'center', name: '村级中心定位', group: '数据获取' },
  { id: 'coverage', name: '数据覆盖率', group: '数据获取' },
  // 空间分析
  { id: 'isochrone', name: '等时圈分析', group: '空间分析' },
  { id: 'accessibility', name: '可达性分析', group: '空间分析' },
  { id: 'poi-search', name: 'POI 搜索', group: '空间分析' },
  { id: 'ecological', name: '生态敏感性', group: '空间分析' },
  // 验证检查
  { id: 'facility-validation', name: '设施选址验证', group: '验证检查' },
  { id: 'constraint-validator', name: '约束验证', group: '验证检查', p3Tag: 'P3#13' },
  { id: 'hazard-buffer', name: '灾害缓冲区', group: '验证检查', p3Tag: 'P3#9' },
  // 规划生成
  { id: 'spatial-layout', name: '空间布局生成', group: '规划生成', p3Tag: 'P3#12+#9' },
  { id: 'landuse-change', name: '用地变化分析', group: '规划生成', p3Tag: 'P3#13' },
];

// ============================================
// Test result tracking
// ============================================

interface TestResult {
  toolId: string;
  toolName: string;
  passed: boolean;
  duration_ms: number;
  error?: string;
  p3Tag?: string;
}

const results: TestResult[] = [];

function record(tool: ToolDef, passed: boolean, duration_ms: number, error?: string) {
  results.push({ toolId: tool.id, toolName: tool.name, passed, duration_ms, error, p3Tag: tool.p3Tag });
  const tag = tool.p3Tag ? ` [${tool.p3Tag}]` : '';
  const status = passed ? 'PASS' : 'FAIL';
  console.log(`  [${status}] ${tool.name}${tag} (${duration_ms}ms)${error ? ` — ${error}` : ''}`);
}

// ============================================
// Screenshot helper
// ============================================

function ensureDir(dir: string) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

async function screenshot(page: Page, name: string): Promise<string> {
  const filepath = path.join(SCREENSHOT_DIR, `gis-e2e-${name}.png`);
  await page.screenshot({ path: filepath, fullPage: true });
  return filepath;
}

// ============================================
// Tool interaction helpers
// ============================================

async function expandGroup(page: Page, groupName: string): Promise<void> {
  // Click the group header button that contains the group name text
  const groupBtn = page.locator(`button:has(span:has-text("${groupName}"))`).first();
  const count = await groupBtn.count();
  if (count > 0) {
    await groupBtn.click();
    await page.waitForTimeout(500);
  }
}

async function expandTool(page: Page, toolName: string): Promise<void> {
  // Click the tool name button inside a border card
  const toolBtn = page.locator(`div.border.rounded-lg.p-3 >> button:has(span:has-text("${toolName}"))`).first();
  const count = await toolBtn.count();
  if (count > 0) {
    await toolBtn.click();
    await page.waitForTimeout(500);
  }
}

async function clickRunButton(page: Page): Promise<boolean> {
  // The "运行测试" button is only visible when a tool is expanded
  const runBtn = page.locator('button:has-text("运行测试"):not([disabled])').first();
  const count = await runBtn.count();
  if (count > 0) {
    await runBtn.click();
    return true;
  }
  return false;
}

async function waitForResult(page: Page, timeoutMs: number): Promise<'success' | 'fail' | 'timeout'> {
  const startTime = Date.now();

  // Wait for spinner to appear (the test was just started)
  const spinnerAppeared = await page.waitForSelector('.animate-spin', { timeout: 5000 }).catch(() => null);

  // Now wait for spinner to disappear (test finished)
  while (Date.now() - startTime < timeoutMs) {
    const spinner = page.locator('.animate-spin');
    const spinnerCount = await spinner.count();

    if (spinnerCount === 0 && spinnerAppeared) {
      // Spinner disappeared after appearing — test is done
      // Check for success (green timing text) or fail (red FAIL text) in expanded tool
      const successEl = page.locator('span.text-green-500');
      const successCount = await successEl.count();
      if (successCount > 0) return 'success';

      const failEl = page.locator('span.text-red-500');
      const failCount = await failEl.count();
      if (failCount > 0) return 'fail';

      // No spinner, no success/fail indicator — might be a different state
      return 'fail';
    }

    await page.waitForTimeout(2000);
  }

  return 'timeout';
}

async function checkMapCanvas(page: Page): Promise<boolean> {
  const canvas = page.locator('canvas');
  const count = await canvas.count();
  return count > 0;
}

// ============================================
// Run a single tool
// ============================================

async function runTool(page: Page, tool: ToolDef): Promise<void> {
  const t0 = Date.now();

  // Expand group
  await expandGroup(page, tool.group);

  // Expand tool
  await expandTool(page, tool.name);

  // Click run
  const clicked = await clickRunButton(page);
  if (!clicked) {
    record(tool, false, Date.now() - t0, '运行测试 button not found');
    return;
  }

  // Wait for result
  const outcome = await waitForResult(page, TOOL_TIMEOUT_MS);
  const elapsed = Date.now() - t0;

  if (outcome === 'success') {
    record(tool, true, elapsed);
  } else if (outcome === 'fail') {
    // Try to get error text
    const errorEl = page.locator('.text-red-600.bg-red-50');
    const errorText = await errorEl.first().textContent().catch(() => 'unknown error');
    record(tool, false, elapsed, errorText?.slice(0, 100));
  } else {
    record(tool, false, elapsed, 'timeout');
  }

  // Screenshot
  await screenshot(page, tool.id);
}

// ============================================
// Report generation
// ============================================

function generateReport(): void {
  const date = new Date().toISOString().split('T')[0];
  const reportPath = path.join(SCREENSHOT_DIR, `${date}-gis-e2e-playwright.md`);

  const passed = results.filter(r => r.passed).length;
  const failed = results.filter(r => !r.passed).length;
  const total = results.length;

  const p3Results = results.filter(r => r.p3Tag);
  const p3Passed = p3Results.filter(r => r.passed).length;

  const rows = results.map(r => {
    const tag = r.p3Tag ? ` [${r.p3Tag}]` : '';
    const status = r.passed ? 'PASS' : 'FAIL';
    return `| ${r.toolName}${tag} | ${status} | ${r.duration_ms}ms | ${r.error || ''} |`;
  }).join('\n');

  const markdown = `# GIS E2E Playwright Test Report

**Date**: ${new Date().toLocaleString()}
**Page**: ${BASE_URL}

## Summary

| Metric | Value |
|--------|-------|
| Total | ${total} |
| Passed | ${passed} |
| Failed | ${failed} |
| P3 Tests | ${p3Passed}/${p3Results.length} |

## Results

| Tool | Status | Duration | Error |
|------|--------|----------|-------|
${rows}

## Screenshots

${results.map(r => `- ${r.toolName}: gis-e2e-${r.toolId}.png`).join('\n')}

## P3 Improvements Verified

| P3 Item | Tool | Status |
|---------|------|--------|
${p3Results.map(r => `| ${r.p3Tag} | ${r.toolName} | ${r.passed ? 'PASS' : 'FAIL'} |`).join('\n')}
`;

  fs.writeFileSync(reportPath, markdown, 'utf-8');
  console.log(`\nReport: ${reportPath}`);
}

// ============================================
// Main
// ============================================

async function main(): Promise<void> {
  ensureDir(SCREENSHOT_DIR);

  console.log('GIS E2E Playwright Test');
  console.log('========================\n');
  console.log(`Target: ${BASE_URL}\n`);

  const browser: Browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Capture API responses for spatial-layout verification
  const apiResponses: Record<string, any> = {};
  page.on('response', async (response) => {
    const url = response.url();
    if (url.includes('/api/dev/gis/')) {
      try {
        const body = await response.json();
        const toolId = url.split('/api/dev/gis/')[1]?.split('?')[0];
        apiResponses[toolId] = { status: response.status(), body };
      } catch { /* ignore */ }
    }
  });

  try {
    // Step 0: Navigate
    console.log('--- Step 0: Page Load ---');
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    // Wait for the page to actually render (Next.js hydration + map)
    await page.waitForSelector('button', { timeout: 30_000 });
    await page.waitForTimeout(3000);
    await screenshot(page, 'page-loaded');
    console.log('  Page loaded\n');

    // Step 1: Run all tools
    for (const tool of TOOLS) {
      const tag = tool.p3Tag ? ` [${tool.p3Tag}]` : '';
      console.log(`--- Running: ${tool.name}${tag} ---`);
      await runTool(page, tool);
      console.log('');
    }

    // Step 2: Verify map canvas after all tools
    console.log('--- Map Canvas Check ---');
    const hasMap = await checkMapCanvas(page);
    console.log(`  Map canvas rendered: ${hasMap}\n`);

    // Step 3: Final screenshot
    await screenshot(page, 'all-tools-complete');

    // Step 4: Verify spatial-layout API response
    console.log('--- API Response Verification ---');
    const layoutResp = apiResponses['spatial-layout'];
    if (layoutResp) {
      console.log(`  spatial-layout API status: ${layoutResp.status}`);
      const body = layoutResp.body;
      if (body?.success) {
        const layerCount = body.layout_configs?.length ?? 0;
        const hasKg = body.kg_built === true;
        console.log(`  layout_configs: ${layerCount} layers`);
        console.log(`  kg_built: ${hasKg}`);
      }
    } else {
      console.log('  spatial-layout API response not captured');
    }

    // Step 5: Summary
    console.log('\n========================');
    console.log('GIS E2E Playwright Results');
    console.log('========================');

    const passed = results.filter(r => r.passed).length;
    const failed = results.filter(r => !r.passed).length;
    console.log(`Total:  ${results.length}`);
    console.log(`Passed: ${passed}`);
    console.log(`Failed: ${failed}`);

    const p3Results = results.filter(r => r.p3Tag);
    if (p3Results.length > 0) {
      console.log(`\nP3 Improvements:`);
      for (const r of p3Results) {
        const status = r.passed ? 'PASS' : 'FAIL';
        console.log(`  [${status}] ${r.p3Tag} — ${r.toolName}`);
      }
    }

    console.log(`\nScreenshots: ${SCREENSHOT_DIR}`);

    // Step 6: Generate report
    generateReport();

    if (failed > 0) {
      console.log('\nSome tests FAILED — check screenshots and report.');
    } else {
      console.log('\nAll tests PASSED!');
    }

  } catch (err) {
    console.error('Test execution error:', err);
    await screenshot(page, 'error');
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
