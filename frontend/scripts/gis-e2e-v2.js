/**
 * GIS E2E Test v2 - CDP + puppeteer-core
 *
 * Key fixes:
 * 1. bringToFront() before every screenshot
 * 2. Wait for map tiles to load after layer toggle
 * 3. Full-page + map-only screenshots
 * 4. API test results saved
 *
 * Run: node scripts/gis-e2e-v2.js
 */

const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', 'test-screenshots');
const CDP_URL = 'http://localhost:9222';
const PAGE_URL = 'http://localhost:3000/test-gis';
const API_BASE = 'http://localhost:8000';

if (!fs.existsSync(DIR)) fs.mkdirSync(DIR, { recursive: true });

const results = { api: {}, browser: {} };

// ============================================
// Helper: Screenshot with bringToFront fix
// ============================================
async function screenshot(page, name, opts = {}) {
  try {
    await page.bringToFront();
    await new Promise(r => setTimeout(r, 800));

    // Full viewport screenshot
    const buf = await page.screenshot({
      type: 'png',
      fullPage: false,
      timeout: 30000,
    });
    const filepath = path.join(DIR, `${name}.png`);
    fs.writeFileSync(filepath, buf);
    console.log(`  Screenshot: ${name}.png (${(buf.length / 1024).toFixed(0)}KB)`);

    // Also capture map-only if requested
    if (opts.mapOnly) {
      try {
        const mapBuf = await page.screenshot({
          type: 'png',
          fullPage: false,
          clip: await page.evaluate(() => {
            const mapEl = document.querySelector('.maplibregl-map');
            if (!mapEl) return null;
            const r = mapEl.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
          }),
          timeout: 15000,
        });
        if (mapBuf) {
          const mapPath = path.join(DIR, `${name}-map.png`);
          fs.writeFileSync(mapPath, mapBuf);
          console.log(`  Map screenshot: ${name}-map.png (${(mapBuf.length / 1024).toFixed(0)}KB)`);
        }
      } catch (e) {
        console.log(`  Map screenshot failed: ${e.message?.substring(0, 60)}`);
      }
    }

    return filepath;
  } catch (e) {
    console.log(`  Screenshot ${name} failed: ${e.message?.substring(0, 80)}`);
    return null;
  }
}

// ============================================
// Helper: API test
// ============================================
async function testApi(name, endpoint, method = 'GET', body = null) {
  const t0 = Date.now();
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${endpoint}`, opts);
    const data = await res.json();
    const timing = Date.now() - t0;
    const success = data.success !== false && res.status >= 200 && res.status < 300;
    results.api[name] = { success, timing_ms: timing, status: res.status };

    let summary = '';
    if (data.geojson) summary = `GeoJSON ${data.geojson.features?.length || 0} features`;
    else if (data.center) summary = `center=[${data.center.join(', ')}]`;
    else if (data.coverage_rate !== undefined) summary = `coverage=${(data.coverage_rate * 100).toFixed(1)}%`;
    else if (data.layout_configs) summary = `${data.layout_configs.length} layouts`;
    else if (data.error) summary = `error: ${data.error.substring(0, 80)}`;

    console.log(`  [API] ${name}: ${success ? 'PASS' : 'FAIL'} ${timing}ms ${summary}`);
    if (!success && data.error) results.api[name].error = data.error;
    return data;
  } catch (e) {
    const timing = Date.now() - t0;
    results.api[name] = { success: false, timing_ms: timing, error: e.message };
    console.log(`  [API] ${name}: FAIL ${timing}ms - ${e.message?.substring(0, 80)}`);
    return null;
  }
}

// ============================================
// Helper: Run frontend tool test
// ============================================
async function runToolTest(page, groupName, toolName) {
  const t0 = Date.now();
  try {
    // Expand tool group
    const groupClicked = await page.evaluate((gn) => {
      const btns = document.querySelectorAll('button.w-full.px-4.py-3');
      for (const btn of btns) {
        if (btn.textContent?.includes(gn)) { btn.click(); return true; }
      }
      return false;
    }, groupName);
    await new Promise(r => setTimeout(r, 600));

    // Expand tool item
    const toolClicked = await page.evaluate((tn) => {
      const btns = document.querySelectorAll('div.border.rounded-lg.p-3 button.w-full');
      for (const btn of btns) {
        if (btn.textContent?.includes(tn)) { btn.click(); return true; }
      }
      return false;
    }, toolName);
    await new Promise(r => setTimeout(r, 600));

    // Click run button
    const runClicked = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const runBtn = btns.find(b => b.textContent?.includes('运行测试') && !b.disabled);
      if (runBtn) { runBtn.click(); return true; }
      return false;
    });

    if (!runClicked) {
      console.log(`  ${toolName}: run button not found`);
      results.browser[toolName] = { success: false, error: 'run button not found', timing_ms: Date.now() - t0 };
      return false;
    }

    console.log(`  Running ${toolName}...`);

    // Wait for completion (max 90s)
    const startTime = Date.now();
    while (Date.now() - startTime < 90000) {
      await new Promise(r => setTimeout(r, 2000));
      const hasSpinner = await page.evaluate(() =>
        document.querySelectorAll('.animate-spin').length > 0
      );
      if (!hasSpinner) break;
    }
    const elapsed = Date.now() - startTime;

    // Get result text
    const resultInfo = await page.evaluate(() => {
      const greens = document.querySelectorAll('.bg-green-50');
      const reds = document.querySelectorAll('.bg-red-50');
      const lastResult = greens.length > 0
        ? greens[greens.length - 1]?.textContent?.substring(0, 120)
        : reds.length > 0 ? reds[reds.length - 1]?.textContent?.substring(0, 120) : 'no result';
      return {
        passed: greens.length,
        failed: reds.length,
        lastResult,
      };
    });

    const success = resultInfo.passed > resultInfo.failed;
    results.browser[toolName] = { success, timing_ms: elapsed, passed: resultInfo.passed, failed: resultInfo.failed };
    console.log(`  ${toolName}: ${(elapsed / 1000).toFixed(1)}s - ${success ? 'PASS' : 'FAIL'} (passed:${resultInfo.passed} failed:${resultInfo.failed})`);
    if (resultInfo.lastResult) console.log(`    Result: ${resultInfo.lastResult}`);
    return success;
  } catch (e) {
    results.browser[toolName] = { success: false, timing_ms: Date.now() - t0, error: e.message };
    console.log(`  ${toolName} error: ${e.message?.substring(0, 80)}`);
    return false;
  }
}

// ============================================
// Main
// ============================================
async function main() {
  console.log('=== GIS E2E Test v2 ===\n');

  // Phase 0: Backend API tests
  console.log('Phase 0: Backend API Tests');
  await testApi('status', '/api/dev/gis/status');
  await testApi('data-fetch', '/api/dev/gis/data-fetch', 'POST', { location: '金田村委会', buffer_km: 5 });
  await testApi('center', '/api/dev/gis/center', 'POST', { location: '金田村委会' });
  await testApi('coverage', '/api/dev/gis/coverage', 'POST', { location: '金田村', buffer_km: 5 });
  await testApi('isochrone', '/api/dev/gis/isochrone', 'POST', { center: [116.044146, 24.818629], time_minutes: [5, 10, 15], travel_mode: 'walk' });
  await testApi('accessibility', '/api/dev/gis/accessibility', 'POST', { analysis_type: 'service_coverage' });
  await testApi('poi-search', '/api/dev/gis/poi-search', 'POST', { keyword: '学校', center: [116.044146, 24.818629], radius: 2000 });
  await testApi('ecological', '/api/dev/gis/ecological', 'POST', { use_jintian_data: true });
  await testApi('facility-validation', '/api/dev/gis/facility-validation', 'POST', { facility_type: '公共服务设施' });
  await testApi('constraint-validator', '/api/dev/gis/constraint-validator', 'POST', { strict_mode: false });
  await testApi('hazard-buffer', '/api/dev/gis/hazard-buffer', 'POST', { buffer_meters: 200 });
  await testApi('spatial-layout', '/api/dev/gis/spatial-layout', 'POST', { village_name: '金田村委会' });
  await testApi('landuse-change', '/api/dev/gis/landuse-change', 'POST', { location: '金田村' });

  // API summary
  const apiPass = Object.values(results.api).filter(r => r.success).length;
  const apiFail = Object.values(results.api).filter(r => !r.success).length;
  console.log(`\nAPI: ${apiPass} PASS, ${apiFail} FAIL\n`);

  // Phase 1: Connect browser
  console.log('Phase 1: Connect Browser');
  let browser, page;
  try {
    browser = await puppeteer.connect({
      browserURL: CDP_URL,
      protocolTimeout: 600000,
    });
    const pages = await browser.pages();
    page = pages[0];
    await page.bringToFront();

    if (!page.url().includes('test-gis')) {
      await page.goto(PAGE_URL, { waitUntil: 'load', timeout: 30000 });
    }
    await new Promise(r => setTimeout(r, 5000));
    console.log('  Connected. URL:', page.url());
  } catch (e) {
    console.error('  Connection failed:', e.message);
    // Save partial results
    fs.writeFileSync(path.join(DIR, 'test-results-v2.json'), JSON.stringify(results, null, 2));
    process.exit(1);
  }

  // Phase 2: Page load
  console.log('\nPhase 2: Page Load');
  await page.bringToFront();
  await new Promise(r => setTimeout(r, 2000));
  await screenshot(page, 'v2-01-page', { mapOnly: true });

  // Phase 3: Enable layers
  console.log('\nPhase 3: Enable Layers');
  await page.evaluate(() => {
    const cbs = document.querySelectorAll('input[type="checkbox"]');
    for (const cb of cbs) {
      const label = cb.parentElement?.textContent || '';
      if (label.includes('boundary') || label.includes('road_current') || label.includes('landuse_current') || label.includes('admin_boundary')) {
        if (!cb.checked) cb.click();
      }
    }
  });
  await new Promise(r => setTimeout(r, 6000));
  await screenshot(page, 'v2-02-layers', { mapOnly: true });

  // Phase 4: Tool tests - Data Fetch group
  console.log('\nPhase 4: Data Fetch Tests');
  await runToolTest(page, '数据获取', 'GIS 数据获取');
  await screenshot(page, 'v2-03-data-fetch', { mapOnly: true });

  await runToolTest(page, '数据获取', '村级中心定位');
  await screenshot(page, 'v2-03-center', { mapOnly: true });

  await runToolTest(page, '数据获取', '数据覆盖率');
  await screenshot(page, 'v2-03-coverage', { mapOnly: true });

  // Phase 5: Spatial Analysis group
  console.log('\nPhase 5: Spatial Analysis Tests');

  await runToolTest(page, '空间分析', '等时圈分析');
  await screenshot(page, 'v2-04-isochrone', { mapOnly: true });

  await runToolTest(page, '空间分析', '可达性分析');
  await screenshot(page, 'v2-04-accessibility', { mapOnly: true });

  await runToolTest(page, '空间分析', 'POI 搜索');
  await screenshot(page, 'v2-04-poi', { mapOnly: true });

  await runToolTest(page, '空间分析', '生态敏感性');
  await screenshot(page, 'v2-04-ecological', { mapOnly: true });

  // Phase 6: Validation group
  console.log('\nPhase 6: Validation Tests');

  await runToolTest(page, '验证检查', '设施选址验证');
  await screenshot(page, 'v2-05-facility', { mapOnly: true });

  await runToolTest(page, '验证检查', '约束验证');
  await screenshot(page, 'v2-05-constraint', { mapOnly: true });

  await runToolTest(page, '验证检查', '灾害缓冲区');
  await screenshot(page, 'v2-05-hazard', { mapOnly: true });

  // Phase 7: Planning group
  console.log('\nPhase 7: Planning Tests');

  await runToolTest(page, '规划生成', '空间布局生成');
  await screenshot(page, 'v2-06-spatial-layout', { mapOnly: true });

  await runToolTest(page, '规划生成', '用地变化分析');
  await screenshot(page, 'v2-06-landuse-change', { mapOnly: true });

  // Phase 8: Final
  console.log('\nPhase 8: Final');
  await screenshot(page, 'v2-08-final', { mapOnly: true });

  // Summary
  console.log('\n=== SUMMARY ===');
  console.log(`API: ${apiPass}/${apiPass + apiFail} passed`);
  const brPass = Object.values(results.browser).filter(r => r.success).length;
  const brFail = Object.values(results.browser).filter(r => !r.success).length;
  console.log(`Browser: ${brPass}/${brPass + brFail} passed`);

  for (const [name, r] of Object.entries(results.browser)) {
    console.log(`  ${r.success ? 'PASS' : 'FAIL'} ${name}: ${r.timing_ms}ms${r.error ? ' - ' + r.error.substring(0, 60) : ''}`);
  }

  fs.writeFileSync(path.join(DIR, 'test-results-v2.json'), JSON.stringify(results, null, 2));
  browser.disconnect();
  console.log('\n=== Done ===');
}

main().catch(e => console.error('Fatal:', e));
