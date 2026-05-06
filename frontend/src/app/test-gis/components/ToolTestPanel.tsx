'use client';

import { useState } from 'react';
import { dataApi } from '@/lib/api/data-api';

interface ToolConfig {
  id: string;
  name: string;
  description: string;
  params: Array<{
    key: string;
    label: string;
    type: 'text' | 'number' | 'select' | 'coords';
    default: any;
    options?: Array<{ value: string; label: string }>;
  }>;
}

const GIS_TOOLS: ToolConfig[] = [
  {
    id: 'isochrone',
    name: '等时圈分析',
    description: '计算指定中心点的可达范围',
    params: [
      { key: 'center', label: '中心坐标', type: 'coords', default: [116.044146, 24.818629] },
      { key: 'time_minutes', label: '时间范围', type: 'text', default: '5,10,15' },
      { key: 'travel_mode', label: '出行方式', type: 'select', default: 'walk', options: [
        { value: 'walk', label: '步行' },
        { value: 'drive', label: '驾车' },
      ]},
    ],
  },
  {
    id: 'accessibility',
    name: '可达性分析',
    description: '分析目的地可达性（支持等时圈和POI）',
    params: [
      { key: 'analysis_type', label: '分析类型', type: 'select', default: 'service_coverage', options: [
        { value: 'service_coverage', label: '服务覆盖' },
        { value: 'route_analysis', label: '路径分析' },
        { value: 'isochrone', label: '等时圈' },
      ]},
    ],
  },
  {
    id: 'poi-search',
    name: 'POI 搜索',
    description: '搜索周边设施',
    params: [
      { key: 'keyword', label: '关键词', type: 'text', default: '学校' },
      { key: 'region', label: '区域', type: 'text', default: '金田村' },
    ],
  },
  {
    id: 'gis-coverage',
    name: 'GIS 覆盖率',
    description: '计算数据覆盖率',
    params: [
      { key: 'location', label: '位置', type: 'text', default: '金田村' },
      { key: 'buffer_km', label: '缓冲区', type: 'number', default: 5 },
    ],
  },
  {
    id: 'ecological',
    name: '生态敏感性',
    description: '评估生态敏感区域（含地质灾害）',
    params: [
      { key: 'use_jintian_data', label: '使用金田数据', type: 'select', default: 'true', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
    ],
  },
  {
    id: 'facility',
    name: '设施验证',
    description: '验证设施选址合理性（含保护约束检查）',
    params: [
      { key: 'facility_type', label: '设施类型', type: 'text', default: '公共服务设施' },
      { key: 'location', label: '坐标', type: 'coords', default: [116.044146, 24.818629] },
    ],
  },
  {
    id: 'vectorizer',
    name: '规划矢量化',
    description: '将规划方案转为 GeoJSON',
    params: [
      { key: 'use_report_data', label: '使用报告数据', type: 'select', default: 'true', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
    ],
  },
  {
    id: 'spatial-layout',
    name: '空间布局',
    description: '生成空间布局方案（支持约束避让）',
    params: [
      { key: 'village_name', label: '村庄名称', type: 'text', default: '金田村委会' },
    ],
  },
  {
    id: 'boundary-fallback',
    name: '边界兜底',
    description: '测试边界生成策略',
    params: [
      { key: 'force_bbox', label: '强制 bbox', type: 'select', default: 'false', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
    ],
  },
  // 新增工具
  {
    id: 'landuse-change',
    name: '用地变化分析',
    description: '分析现状用地与规划用地变化',
    params: [
      { key: 'use_jintian_data', label: '使用金田数据', type: 'select', default: 'true', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
      { key: 'change_threshold', label: '变化阈值', type: 'number', default: 0.1 },
    ],
  },
  {
    id: 'constraint-validator',
    name: '约束验证',
    description: '验证规划方案是否符合保护约束',
    params: [
      { key: 'use_jintian_data', label: '使用金田数据', type: 'select', default: 'true', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
      { key: 'strict_mode', label: '严格模式', type: 'select', default: 'false', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
    ],
  },
  {
    id: 'hazard-buffer',
    name: '灾害缓冲区',
    description: '生成地质灾害缓冲区',
    params: [
      { key: 'use_jintian_data', label: '使用金田数据', type: 'select', default: 'true', options: [
        { value: 'true', label: '是' },
        { value: 'false', label: '否' },
      ]},
      { key: 'buffer_meters', label: '缓冲距离(米)', type: 'number', default: 200 },
    ],
  },
];

interface ToolTestPanelProps {
  onTestComplete?: (toolId: string, result: any) => void;
}

export default function ToolTestPanel({ onTestComplete }: ToolTestPanelProps) {
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, Record<string, any>>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleToolSelect = (toolId: string) => {
    setSelectedTool(toolId);
    const tool = GIS_TOOLS.find(t => t.id === toolId);
    if (tool && !params[toolId]) {
      const defaultParams: Record<string, any> = {};
      tool.params.forEach(p => {
        defaultParams[p.key] = p.default;
      });
      setParams(prev => ({ ...prev, [toolId]: defaultParams }));
    }
  };

  const handleParamChange = (toolId: string, key: string, value: any) => {
    setParams(prev => ({
      ...prev,
      [toolId]: { ...prev[toolId], [key]: value },
    }));
  };

  const runTest = async (toolId: string) => {
    setRunning(toolId);
    setErrors(prev => ({ ...prev, [toolId]: '' }));

    try {
      const toolParams = params[toolId] || {};
      let result: any;

      switch (toolId) {
        case 'isochrone':
          const timesStr = toolParams.time_minutes || '5,10,15';
          const times = timesStr.split(',').map(Number);
          result = await dataApi.testIsochrone({
            center: toolParams.center,
            time_minutes: times,
            travel_mode: toolParams.travel_mode,
          });
          break;

        case 'accessibility':
          result = await dataApi.testAccessibility({
            analysis_type: toolParams.analysis_type,
          });
          break;

        case 'poi-search':
          result = await dataApi.testPOISearch({
            keyword: toolParams.keyword,
            region: toolParams.region,
          });
          break;

        case 'gis-coverage':
          result = await dataApi.testGISCoverage({
            location: toolParams.location,
            buffer_km: Number(toolParams.buffer_km),
          });
          break;

        case 'ecological':
          result = await dataApi.testEcological({
            use_jintian_data: toolParams.use_jintian_data === 'true',
          });
          break;

        case 'facility':
          result = await dataApi.testFacility({
            facility_type: toolParams.facility_type,
            location: toolParams.location,
          });
          break;

        case 'vectorizer':
          result = await dataApi.testVectorizer({
            use_report_data: toolParams.use_report_data === 'true',
          });
          break;

        case 'spatial-layout':
          result = await dataApi.testSpatialLayout(toolParams.village_name);
          break;

        case 'boundary-fallback':
          result = await dataApi.testBoundaryFallback(toolParams.village_name || '金田村委会', {
            force_bbox: toolParams.force_bbox === 'true',
          });
          break;

        // 新增工具测试
        case 'landuse-change':
          result = await dataApi.testLanduseChange({
            use_jintian_data: toolParams.use_jintian_data === 'true',
            change_threshold: Number(toolParams.change_threshold),
          });
          break;

        case 'constraint-validator':
          result = await dataApi.testConstraintValidator({
            use_jintian_data: toolParams.use_jintian_data === 'true',
            strict_mode: toolParams.strict_mode === 'true',
          });
          break;

        case 'hazard-buffer':
          result = await dataApi.testHazardBuffer({
            use_jintian_data: toolParams.use_jintian_data === 'true',
            buffer_meters: Number(toolParams.buffer_meters),
          });
          break;

        default:
          throw new Error(`Unknown tool: ${toolId}`);
      }

      setResults(prev => ({ ...prev, [toolId]: result }));
      onTestComplete?.(toolId, result);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Unknown error';
      setErrors(prev => ({ ...prev, [toolId]: errorMsg }));
    } finally {
      setRunning(null);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-sm">
      <div className="p-4 border-b">
        <h3 className="font-semibold text-gray-800">GIS 工具测试</h3>
        <p className="text-sm text-gray-500 mt-1">
          {GIS_TOOLS.length} 个工具可用
        </p>
      </div>

      <div className="divide-y max-h-[400px] overflow-y-auto">
        {GIS_TOOLS.map(tool => (
          <div key={tool.id} className="p-3">
            <button
              onClick={() => handleToolSelect(tool.id)}
              className="w-full flex items-center justify-between"
            >
              <div>
                <span className="font-medium text-gray-700">{tool.name}</span>
                <p className="text-xs text-gray-500 mt-0.5">{tool.description}</p>
              </div>
              <svg
                className={`w-4 h-4 text-gray-400 transition-transform ${
                  selectedTool === tool.id ? 'rotate-180' : ''
                }`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {selectedTool === tool.id && (
              <div className="mt-3 space-y-2">
                {tool.params.map(param => (
                  <div key={param.key} className="flex items-center gap-2">
                    <label className="text-sm text-gray-600 w-24">{param.label}</label>
                    {param.type === 'select' ? (
                      <select
                        value={params[tool.id]?.[param.key] || param.default}
                        onChange={(e) => handleParamChange(tool.id, param.key, e.target.value)}
                        className="flex-1 px-2 py-1 border rounded text-sm"
                      >
                        {param.options?.map(opt => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    ) : param.type === 'coords' ? (
                      <input
                        type="text"
                        value={Array.isArray(params[tool.id]?.[param.key])
                          ? (params[tool.id]?.[param.key] as number[]).join(',')
                          : String(params[tool.id]?.[param.key] || param.default)}
                        onChange={(e) => {
                          const val = e.target.value.split(',').map(Number);
                          handleParamChange(tool.id, param.key, val);
                        }}
                        className="flex-1 px-2 py-1 border rounded text-sm"
                      />
                    ) : (
                      <input
                        type={param.type === 'number' ? 'number' : 'text'}
                        value={params[tool.id]?.[param.key] ?? param.default}
                        onChange={(e) => handleParamChange(
                          tool.id,
                          param.key,
                          param.type === 'number' ? Number(e.target.value) : e.target.value
                        )}
                        className="flex-1 px-2 py-1 border rounded text-sm"
                      />
                    )}
                  </div>
                ))}

                <button
                  onClick={() => runTest(tool.id)}
                  disabled={running === tool.id}
                  className={`w-full py-2 rounded text-sm font-medium ${
                    running === tool.id
                      ? 'bg-gray-200 text-gray-500'
                      : 'bg-blue-500 text-white hover:bg-blue-600'
                  }`}
                >
                  {running === tool.id ? '运行中...' : '运行测试'}
                </button>

                {errors[tool.id] && (
                  <div className="text-sm text-red-600 bg-red-50 p-2 rounded">
                    {errors[tool.id]}
                  </div>
                )}

                {results[tool.id]?.success && (
                  <div className="text-sm text-green-600 bg-green-50 p-2 rounded">
                    测试成功
                    {results[tool.id].geojson && (
                      <span className="ml-1">
                        · GeoJSON: {results[tool.id].geojson?.features?.length || 0} 个要素
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}