/**
 * GIS E2E Test - 通过 CDP 连接 Chrome，使用 puppeteer-core
 *
 * 修复方案（基于 exa 搜索结果）：
 * 1. connectOverCDP 时设置 protocolTimeout: 600000 (10min)
 * 2. 截图前调用 page.bringToFront() 激活标签页
 * 3. 使用 chrome-headless-shell 避免 Chrome 147+ 截图回归
 *
 * 运行: node scripts/gis-e2e-test.js
 */

const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const DIR = path.join(__dirname, '..', 'test-screenshots');
const CDP_URL = 'http://localhost:9222';
const PAGE_URL = 'http://localhost:3000/test-gis';
const API_BASE = 'http://localhost:8000';

if (!fs.existsSync(DIR)) fs.mkdirSync(DIR, { recursive: true });

const testResults = {};

// ============================================
// Helper: 截图（带修复）
// ============================================
async function takeScreenshot(page, name) {
  try {
    // 关键修复：激活标签页后再截图
    await page.bringToFront();
    await new Promise(r => setTimeout(r, 500));

    const buf = await page.screenshot({
      type: 'png',
      fullPage: false,
      timeout: 30000,
    });
    const filepath = path.join(DIR, `${name}.png`);
    fs.writeFileSync(filepath, buf);
    console.log(`  Screenshot: ${name}.png (${(buf.length / 1024).toFixed(0)}KB)`);
    return filepath;
  } catch (e) {
    console.log(`  Screenshot ${name} failed: ${e.message?.substring(0, 100)}`);
    return null;
  }
}

// ============================================
// Helper: 后端 API 测试
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
    testResults[name] = { success, timing_ms: timing, status: res.status };

    // 提取关键信息
    let summary = '';
    if (data.geojson) {
      const fc = data.geojson;
      summary = `GeoJSON ${fc.type} ${fc.features?.length || 0} features`;
    } else if (data.center) {
      summary = `center=[${data.center.join(', ')}]`;
    } else if (data.coverage_rate !== undefined) {
      summary = `coverage=${(data.coverage_rate * 100).toFixed(1)}%`;
    } else if (data.layout_configs) {
      summary = `${data.layout_configs.length} layout configs`;
    } else if (data.services) {
      summary = Object.entries(data.services).filter(([,v]) => v).map(([k]) => k).join(',');
    } else if (data.error) {
      summary = `error: ${data.error.substring(0, 60)}`;
    }

    console.log(`  [API] ${name}: ${success ? 'PASS' : 'FAIL'} ${timing}ms ${summary}`);
    if (!success && data.error) {
      testResults[name].error = data.error;
    }
    return data;
  } catch (e) {
    const timing = Date.now() - t0;
    testResults[name] = { success: false, timing_ms: timing, error: e.message };
    console.log(`  [API] ${name}: FAIL ${timing}ms - ${e.message?.substring(0, 80)}`);
    return null;
  }
}

// ============================================
// Helper: 前端工具测试
// ============================================
async function runFrontendToolTest(page, groupName, toolName) {
  try {
    // 展开工具组
    await page.evaluate((gn) => {
      const btns = document.querySelectorAll('button.w-full.px-4.py-3');
      for (const btn of btns) {
        if (btn.textContent?.includes(gn)) { btn.click(); return true; }
      }
      return false;
    }, groupName);
    await new Promise(r => setTimeout(r, 500));

    // 展开工具
    await page.evaluate((tn) => {
      const btns = document.querySelectorAll('div.border.rounded-lg.p-3 button.w-full');
      for (const btn of btns) {
        if (btn.textContent?.includes(tn)) { btn.click(); return true; }
      }
      return false;
    }, toolName);
    await new Promise(r => setTimeout(r, 500));

    // 点击运行测试
    const runClicked = await page.evaluate(() => {
      const runBtns = Array.from(document.querySelectorAll('button'));
      const runBtn = runBtns.find(b => b.textContent?.includes('运行测试') && !b.disabled);
      if (runBtn) { runBtn.click(); return true; }
      return false;
    });

    if (!runClicked) {
      console.log(`  ${toolName}: 运行按钮未找到`);
      return false;
    }

    console.log(`  运行 ${toolName}...`);

    // 等待完成
    const startTime = Date.now();
    while (Date.now() - startTime < 120000) {
      await new Promise(r => setTimeout(r, 3000));
      const hasSpinner = await page.evaluate(() =>
        document.querySelectorAll('.animate-spin').length > 0
      );
      if (!hasSpinner) break;
    }
    const elapsed = Date.now() - startTime;

    // 获取结果
    const resultText = await page.evaluate(() => {
      const green = document.querySelectorAll('.bg-green-50');
      const red = document.querySelectorAll('.bg-red-50');
      return {
        passed: green.length,
        failed: red.length,
        lastGreen: green.length > 0 ? green[green.length - 1]?.textContent?.substring(0, 80) : null,
        lastRed: red.length > 0 ? red[red.length - 1]?.textContent?.substring(0, 80) : null,
      };
    });

    console.log(`  ${toolName}: ${(elapsed / 1000).toFixed(1)}s - passed:${resultText.passed} failed:${resultText.failed}`);
    if (resultText.lastGreen) console.log(`    成功: ${resultText.lastGreen}`);
    if (resultText.lastRed) console.log(`    失败: ${resultText.lastRed}`);

    return true;
  } catch (e) {
    console.log(`  ${toolName} 错误: ${e.message?.substring(0, 80)}`);
    return false;
  }
}

// ============================================
// Main
// ============================================
async function main() {
  console.log('=== GIS 端到端测试 ===\n');

  // Phase 0: 后端 API 直接测试
  console.log('=== Phase 0: 后端 API 直接测试 ===');
  const status = await testApi('status', '/api/dev/gis/status');
  if (status?.services) {
    const svc = status.services;
    console.log(`  服务: tianditu=${svc.tianditu_api_key} amap=${svc.amap_api_key} osmnx=${svc.osmnx} geopandas=${svc.geopandas} jintian=${svc.jintian_data}`);
  }

  // Phase 1: 连接浏览器
  console.log('\n=== Phase 1: 连接浏览器 ===');
  let browser, page;
  try {
    browser = await puppeteer.connect({
      browserURL: CDP_URL,
      protocolTimeout: 600000,  // 10min，修复 CDP 超时
    });
    const pages = await browser.pages();
    page = pages[0];

    if (!page.url().includes('test-gis')) {
      await page.goto(PAGE_URL, { waitUntil: 'load', timeout: 30000 });
    }
    await new Promise(r => setTimeout(r, 8000));

    // 关键修复：激活标签页
    await page.bringToFront();

    console.log('  已连接 Chrome CDP');
    console.log('  URL:', page.url());
  } catch (e) {
    console.error('  连接失败:', e.message);
    process.exit(1);
  }

  // Phase 2: 页面加载验证
  console.log('\n=== Phase 2: 页面加载验证 ===');
  const pageState = await page.evaluate(() => {
    const h1 = document.querySelector('h1')?.textContent || 'N/A';
    const info = document.querySelector('.text-sm.text-gray-500')?.textContent || 'N/A';
    const mapEl = document.querySelector('.maplibregl-map');
    const checkboxes = document.querySelectorAll('input[type="checkbox"]');
    return { h1, info, hasMap: !!mapEl, checkboxCount: checkboxes.length };
  });
  console.log('  H1:', pageState.h1);
  console.log('  图层信息:', pageState.info);
  console.log('  地图容器:', pageState.hasMap ? '存在' : '不存在');
  console.log('  Checkbox数量:', pageState.checkboxCount);

  await takeScreenshot(page, '01-page-loaded');

  // Phase 3: 标准图层测试
  console.log('\n=== Phase 3: 标准图层测试 ===');

  // 启用关键现状图层
  await page.evaluate(() => {
    const cbs = document.querySelectorAll('input[type="checkbox"]');
    for (const cb of cbs) {
      const label = cb.parentElement?.textContent || '';
      // 只启用现状图层
      if (label.includes('boundary(') || label.includes('road_current') || label.includes('landuse_current') || label.includes('admin_boundary')) {
        if (!cb.checked) cb.click();
      }
    }
  });
  await new Promise(r => setTimeout(r, 8000));

  const layerState = await page.evaluate(() => {
    const info = document.querySelector('.text-sm.text-gray-500')?.textContent || 'N/A';
    const badges = Array.from(document.querySelectorAll('.bg-gray-100.px-1.rounded.text-xs')).map(b => b.textContent);
    return { info, badges };
  });
  console.log('  图层信息:', layerState.info);
  console.log('  图层徽章:', layerState.badges);

  await takeScreenshot(page, '02-standard-layers');

  // Phase 4: 数据获取类测试
  console.log('\n=== Phase 4: 数据获取类测试 ===');
  await testApi('data-fetch', '/api/dev/gis/data-fetch', 'POST', { location: '金田村委会', buffer_km: 5 });
  await testApi('center', '/api/dev/gis/center', 'POST', { location: '金田村委会' });
  await testApi('coverage', '/api/dev/gis/coverage', 'POST', { location: '金田村', buffer_km: 5 });

  // 前端测试: data-fetch
  await runFrontendToolTest(page, '数据获取', 'GIS 数据获取');
  await takeScreenshot(page, '03-data-fetch');

  // Phase 5: 空间分析类测试
  console.log('\n=== Phase 5: 空间分析类测试 ===');
  await testApi('isochrone', '/api/dev/gis/isochrone', 'POST', { center: [116.044146, 24.818629], time_minutes: [5, 10, 15], travel_mode: 'walk' });
  await testApi('accessibility', '/api/dev/gis/accessibility', 'POST', { analysis_type: 'service_coverage' });
  await testApi('poi-search', '/api/dev/gis/poi-search', 'POST', { keyword: '学校', center: [116.044146, 24.818629], radius: 2000 });
  await testApi('ecological', '/api/dev/gis/ecological', 'POST', { use_jintian_data: true });

  // 前端测试: isochrone
  await runFrontendToolTest(page, '空间分析', '等时圈分析');
  await takeScreenshot(page, '04-isochrone');

  // 前端测试: POI搜索
  await runFrontendToolTest(page, '空间分析', 'POI 搜索');
  await takeScreenshot(page, '05-poi-search');

  // Phase 6: 验证检查类测试
  console.log('\n=== Phase 6: 验证检查类测试 ===');
  await testApi('facility-validation', '/api/dev/gis/facility-validation', 'POST', { facility_type: '公共服务设施' });
  await testApi('constraint-validator', '/api/dev/gis/constraint-validator', 'POST', { strict_mode: false });
  await testApi('hazard-buffer', '/api/dev/gis/hazard-buffer', 'POST', { buffer_meters: 200 });

  await runFrontendToolTest(page, '验证检查', '设施选址验证');
  await takeScreenshot(page, '06-validation');

  // Phase 7: 规划生成类测试
  console.log('\n=== Phase 7: 规划生成类测试 ===');
  await testApi('spatial-layout', '/api/dev/gis/spatial-layout', 'POST', { village_name: '金田村委会' });
  await testApi('landuse-change', '/api/dev/gis/landuse-change', 'POST', { location: '金田村' });

  await runFrontendToolTest(page, '规划生成', '空间布局生成');
  await takeScreenshot(page, '07-spatial-layout');

  // Phase 8: 综合验证
  console.log('\n=== Phase 8: 综合验证 ===');

  await takeScreenshot(page, '08-final');

  // 汇总
  console.log('\n=== 测试汇总 ===');
  let passed = 0, failed = 0;
  for (const [name, result] of Object.entries(testResults)) {
    const icon = result.success ? 'PASS' : 'FAIL';
    console.log(`  ${icon} ${name}: ${result.timing_ms}ms${result.error ? ' - ' + result.error.substring(0, 60) : ''}`);
    if (result.success) passed++; else failed++;
  }
  console.log(`\nAPI 测试: ${passed} 通过, ${failed} 失败`);

  // 保存结果
  fs.writeFileSync(path.join(DIR, 'test-results.json'), JSON.stringify(testResults, null, 2));

  browser.disconnect();
  console.log('\n=== 测试完成 ===');
}

main().catch(e => console.error('Fatal:', e));
