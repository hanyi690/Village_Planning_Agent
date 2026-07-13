/**
 * Test village data fixtures for E2E tests.
 * Uses realistic Chinese village data to exercise the full planning pipeline.
 */

export const TEST_VILLAGE = {
  projectName: '桃花村',
  villageName: '桃花村',
  province: '浙江省',
  city: '杭州市',
  county: '余杭区',
  township: '瓶窑镇',
  planningPeriod: '2022-2035年',
  taskDescription: '制定桃花村国土空间规划方案，优化村庄空间布局，提升人居环境质量，促进产业融合发展。',
  constraints: '严格遵守生态保护红线、永久基本农田和城镇开发边界三条控制线。',
  villageData: `
桃花村位于浙江省杭州市余杭区瓶窑镇西南部，距杭州市中心约35公里。

【基本信息】
- 行政区划：下辖桃花坞、李家湾、王家埭3个自然村，共12个村民小组
- 人口：常住人口1852人，户籍人口1968人（2021年统计）
- 村域面积：约5.8平方公里
- 耕地面积：1820亩（其中基本农田1520亩）
- 林地面积：3200亩
- 建设用地：约380亩

【自然地理】
- 地形地貌：低山丘陵与河谷平原交错，海拔8-200米
- 水系：苕溪支流桃花溪穿村而过，村域内有小型水库1座（桃花坞水库，库容35万立方米）
- 气候：亚热带季风气候，年均气温16.2℃，年降水量1450mm

【社会经济】
- 主导产业：水蜜桃种植（800亩）、乡村旅游（年接待游客约5万人次）、竹制品加工
- 村集体年收入：85万元（2021年）
- 农民人均可支配收入：3.2万元（2021年）
- 特色资源：百年桃园、明清古建筑群（3处省保单位）、竹编非遗技艺

【基础设施】
- 对外交通：县道X302穿村，距杭长高速瓶窑出口8公里
- 村内道路：主干道硬化率100%，支路硬化率65%
- 给排水：集中供水覆盖率92%，雨污分流改造率40%
- 电力通信：已覆盖4G网络，光纤入户率75%
- 环卫设施：垃圾收集点8处，公厕3座，无污水处理设施

【公共服务】
- 村委会1处（含卫生室、图书室）
- 小学1所（6个班级，学生186人）
- 老年人活动中心1处
- 文化礼堂1处
- 篮球场2处

【历史文化】
- 明清古建筑群（省保，含3处院落，占地约5800平方米）
- 百年桃园（最老桃树树龄120年）
- 竹编非遗技艺（市级非遗，传承人3人）
- 传统庙会（每年农历三月初三）

【存在问题】
- 村庄建设布局分散，土地集约利用水平低
- 污水处理设施缺乏，桃花溪水质呈下降趋势（III→IV类）
- 旅游配套设施不足，游客承载力有限
- 青年人口外流，老龄化率22%
- 传统建筑缺乏系统保护规划
  `.trim(),
};

/** Minimal village data for fast smoke tests */
export const MINIMAL_VILLAGE = {
  projectName: '测试村',
  villageName: '测试村',
  province: '浙江省',
  city: '杭州市',
  county: '余杭区',
  villageData: '这是一个测试村庄，位于浙江省杭州市余杭区，总面积约5平方公里，下辖3个自然村，人口约2000人，主要产业为农业和乡村旅游。',
  taskDescription: '制定村庄发展规划方案',
  stepMode: true,
};

export const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

/** Jintian GIS test data directory (organized under data/gis/jintian/) */
export const GIS_TEST_DATA_DIR = 'F:/project/Village_Planning_Agent/data/gis/jintian';

/** E2E test output directory */
export const E2E_OUTPUT_BASE = 'F:/project/Village_Planning_Agent/data/gis/jintian/output/e2e';

/** Core 3 Jintian GIS files for upload (现状数据) */
export const JINTIAN_GIS_FILES = {
  boundary: `${GIS_TEST_DATA_DIR}/current/boundary.geojson`,
  landuse: `${GIS_TEST_DATA_DIR}/current/landuse.geojson`,
  road: `${GIS_TEST_DATA_DIR}/current/road.geojson`,
};

/** Full Jintian GIS files for upload (现状 + 规划保护线) */
export const JINTIAN_ALL_GIS_FILES = {
  ...JINTIAN_GIS_FILES,
  construction_zone: `${GIS_TEST_DATA_DIR}/planned/construction_zone.geojson`,
  ecological_protection: `${GIS_TEST_DATA_DIR}/planned/ecological_protection.geojson`,
  farmland_protection: `${GIS_TEST_DATA_DIR}/planned/farmland_protection.geojson`,
  geological_hazard_points: `${GIS_TEST_DATA_DIR}/planned/geological_hazard_points.geojson`,
};

/** Invalid GeoJSON string for error testing */
export const INVALID_GEOJSON_STRING = '{"type":"Invalid","features":[]}';

/** Jintian demo data file path (detailed village report) */
export const JINTIAN_DEMO_DATA_PATH = 'F:/project/Village_Planning_Agent/frontend/public/demo/jintian_village.md';

/** Jintian village full test data with geography. villageData loaded from demo file at runtime. */
export const JINTIAN_VILLAGE = {
  projectName: '金田村',
  villageName: '金田村',
  province: '广东省',
  city: '梅州市',
  county: '平远县',
  township: '泗水镇',
  villageData: '', // Will be loaded from JINTIAN_DEMO_DATA_PATH at runtime
  taskDescription: '制定金田村国土空间规划方案，优化村庄空间布局，提升人居环境质量，促进产业融合发展',
};

/** Load Jintian village detailed data from demo file */
export async function loadJintianVillageData(): Promise<string> {
  const fs = await import('fs/promises');
  return fs.readFile(JINTIAN_DEMO_DATA_PATH, 'utf-8');
}
