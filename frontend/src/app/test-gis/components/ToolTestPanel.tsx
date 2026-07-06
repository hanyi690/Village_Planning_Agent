'use client';

import { useState } from 'react';
import type { GisTestSuiteState } from '../hooks/useGisTestSuite';

// ============================================
// Test Configuration
// ============================================

interface ToolConfig {
  id: string;
  name: string;
  description: string;
  params: Array<{
    key: string;
    label: string;
    type: 'text' | 'number' | 'select' | 'coords';
    default: unknown;
    options?: Array<{ value: string; label: string }>;
  }>;
}

interface ToolGroup {
  name: string;
  color: string;
  tools: ToolConfig[];
}

const TOOL_GROUPS: ToolGroup[] = [
  {
    name: '数据获取',
    color: '#3B82F6',
    tools: [
      {
        id: 'data-fetch',
        name: 'GIS 数据获取',
        description: '获取水系/道路/居民地/边界等全部数据',
        params: [
          { key: 'location', label: '位置', type: 'text', default: '金田村委会' },
          { key: 'buffer_km', label: '缓冲区(km)', type: 'number', default: 5 },
        ],
      },
      {
        id: 'center',
        name: '村级中心定位',
        description: '4层降级策略定位村中心',
        params: [
          { key: 'location', label: '位置', type: 'text', default: '金田村委会' },
        ],
      },
      {
        id: 'coverage',
        name: '数据覆盖率',
        description: '计算 GIS 数据覆盖率和分层统计',
        params: [
          { key: 'location', label: '位置', type: 'text', default: '金田村' },
          { key: 'buffer_km', label: '缓冲区(km)', type: 'number', default: 5 },
        ],
      },
    ],
  },
  {
    name: '空间分析',
    color: '#10B981',
    tools: [
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
        description: '分析目的地可达性',
        params: [
          { key: 'analysis_type', label: '分析类型', type: 'select', default: 'service_coverage', options: [
            { value: 'service_coverage', label: '服务覆盖' },
            { value: 'driving_accessibility', label: '驾车可达' },
            { value: 'walking_accessibility', label: '步行可达' },
          ]},
        ],
      },
      {
        id: 'poi-search',
        name: 'POI 搜索',
        description: '搜索周边设施',
        params: [
          { key: 'keyword', label: '关键词', type: 'text', default: '学校' },
          { key: 'center', label: '中心坐标', type: 'coords', default: [116.044146, 24.818629] },
          { key: 'radius', label: '半径(m)', type: 'number', default: 2000 },
        ],
      },
      {
        id: 'ecological',
        name: '生态敏感性',
        description: '评估生态敏感区域',
        params: [
          { key: 'use_jintian_data', label: '使用金田数据', type: 'select', default: 'true', options: [
            { value: 'true', label: '是' },
            { value: 'false', label: '否' },
          ]},
        ],
      },
    ],
  },
  {
    name: '验证检查',
    color: '#F59E0B',
    tools: [
      {
        id: 'facility-validation',
        name: '设施选址验证',
        description: '验证设施选址合理性',
        params: [
          { key: 'facility_type', label: '设施类型', type: 'text', default: '公共服务设施' },
          { key: 'location', label: '坐标', type: 'coords', default: [116.044146, 24.818629] },
        ],
      },
      {
        id: 'constraint-validator',
        name: '约束验证',
        description: '验证规划方案是否符合保护约束',
        params: [
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
          { key: 'buffer_meters', label: '缓冲距离(米)', type: 'number', default: 200 },
        ],
      },
      {
        id: 'layout-validate',
        name: '布局验证',
        description: '验证布局方案的合规性和冲突',
        params: [
          { key: 'use_jintian_data', label: '使用金田数据', type: 'select', default: 'true', options: [
            { value: 'true', label: '是' },
            { value: 'false', label: '否' },
          ]},
        ],
      },
    ],
  },
  {
    name: '规划生成',
    color: '#8B5CF6',
    tools: [
      {
        id: 'spatial-layout',
        name: '空间布局生成',
        description: '运行完整空间布局管线',
        params: [
          { key: 'village_name', label: '村庄名称', type: 'text', default: '金田村委会' },
        ],
      },
      {
        id: 'landuse-change',
        name: '用地变化分析',
        description: '对比现状与规划用地',
        params: [
          { key: 'location', label: '位置', type: 'text', default: '金田村' },
        ],
      },
    ],
  },
];

// ============================================
// Component
// ============================================

interface ToolTestPanelProps {
  testSuite: GisTestSuiteState;
}

export default function ToolTestPanel({ testSuite }: ToolTestPanelProps) {
  const { results, runningTests, runTest } = testSuite;
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, Record<string, unknown>>>({});

  const handleParamChange = (toolId: string, key: string, value: unknown) => {
    setParams(prev => ({ ...prev, [toolId]: { ...prev[toolId], [key]: value } }));
  };

  const handleRun = async (tool: ToolConfig) => {
    // Build params from UI state, applying type conversions
    const toolParams: Record<string, unknown> = {};
    for (const p of tool.params) {
      const val = params[tool.id]?.[p.key] ?? p.default;
      if (p.type === 'number') {
        toolParams[p.key] = Number(val);
      } else if (p.type === 'select' && typeof val === 'string') {
        toolParams[p.key] = val === 'true' ? true : val === 'false' ? false : val;
      } else if (p.type === 'coords' && typeof val === 'string') {
        toolParams[p.key] = val.split(',').map(Number);
      } else if (p.key === 'time_minutes' && typeof val === 'string') {
        toolParams[p.key] = val.split(',').map(Number);
      } else {
        toolParams[p.key] = val;
      }
    }
    await runTest(tool.id, toolParams);
  };

  return (
    <div className="bg-white rounded-lg shadow-sm">
      <div className="p-4 border-b">
        <h3 className="font-semibold text-gray-800">GIS 工具测试</h3>
        <p className="text-sm text-gray-500 mt-1">
          {TOOL_GROUPS.reduce((n, g) => n + g.tools.length, 0)} 个工具 · {TOOL_GROUPS.length} 个分类
        </p>
      </div>

      <div className="divide-y max-h-[600px] overflow-y-auto">
        {TOOL_GROUPS.map(group => (
          <div key={group.name}>
            <button
              onClick={() => setExpandedGroup(expandedGroup === group.name ? null : group.name)}
              className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50"
            >
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: group.color }} />
                <span className="font-medium text-gray-700">{group.name}</span>
                <span className="text-xs text-gray-400">({group.tools.length})</span>
              </div>
              <svg
                className={`w-4 h-4 text-gray-400 transition-transform ${expandedGroup === group.name ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {expandedGroup === group.name && (
              <div className="px-4 pb-3 space-y-2">
                {group.tools.map(tool => {
                  const isRunning = runningTests.has(tool.id);
                  const result = results[tool.id];
                  const isExpanded = expandedTool === tool.id;

                  return (
                    <div key={tool.id} className="border rounded-lg p-3">
                      <button
                        onClick={() => setExpandedTool(isExpanded ? null : tool.id)}
                        className="w-full flex items-center justify-between"
                      >
                        <div className="text-left">
                          <span className="font-medium text-gray-700 text-sm">{tool.name}</span>
                          <p className="text-xs text-gray-500">{tool.description}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          {result && (
                            result.success
                              ? <span className="text-green-500 text-xs">{result.timing_ms}ms</span>
                              : <span className="text-red-500 text-xs">FAIL</span>
                          )}
                          {isRunning && (
                            <span className="animate-spin inline-block w-3 h-3 border border-blue-500 border-t-transparent rounded-full" />
                          )}
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="mt-3 space-y-2">
                          {tool.params.map(param => (
                            <div key={param.key} className="flex items-center gap-2">
                              <label className="text-xs text-gray-600 w-20">{param.label}</label>
                              {param.type === 'select' ? (
                                <select
                                  value={String(params[tool.id]?.[param.key] ?? param.default)}
                                  onChange={(e) => handleParamChange(tool.id, param.key, e.target.value)}
                                  className="flex-1 px-2 py-1 border rounded text-xs"
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
                                    : String(params[tool.id]?.[param.key] ?? param.default)}
                                  onChange={(e) => handleParamChange(tool.id, param.key, e.target.value)}
                                  className="flex-1 px-2 py-1 border rounded text-xs"
                                />
                              ) : (
                                <input
                                  type={param.type === 'number' ? 'number' : 'text'}
                                  value={String(params[tool.id]?.[param.key] ?? param.default)}
                                  onChange={(e) => handleParamChange(
                                    tool.id, param.key,
                                    param.type === 'number' ? Number(e.target.value) : e.target.value
                                  )}
                                  className="flex-1 px-2 py-1 border rounded text-xs"
                                />
                              )}
                            </div>
                          ))}

                          <button
                            onClick={() => handleRun(tool)}
                            disabled={isRunning}
                            className={`w-full py-1.5 rounded text-xs font-medium ${
                              isRunning ? 'bg-gray-200 text-gray-500' : 'bg-blue-500 text-white hover:bg-blue-600'
                            }`}
                          >
                            {isRunning ? '运行中...' : '运行测试'}
                          </button>

                          {result?.error && (
                            <div className="text-xs text-red-600 bg-red-50 p-2 rounded break-all">
                              {result.error}
                            </div>
                          )}

                          {result?.success && result.data && (
                            <div className="text-xs text-green-600 bg-green-50 p-2 rounded">
                              成功 · {result.timing_ms}ms
                              {result.data.geojson ? (
                                <span> · GeoJSON: {(result.data.geojson as { features?: unknown[] })?.features?.length ?? '?'} 要素</span>
                              ) : null}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
