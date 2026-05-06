'use client';

import { useState, useRef } from 'react';
import type {
  VillagePlanningScheme,
  PlanningZone,
  FacilityPoint,
  DevelopmentAxis,
  LandUseType,
  FacilityStatus,
  DirectionBias,
  DensityLevel,
  PriorityLevel,
  AxisType,
  AxisDirection,
} from '../types/planning';
import { ZONE_TYPE_NAMES, FACILITY_STATUS_COLORS, getZoneColor } from '../types/planning';

// ============================================
// Sub-components
// ============================================

interface ZoneEditorProps {
  zone: PlanningZone;
  onUpdate: (update: Partial<PlanningZone>) => void;
  onRemove: () => void;
}

function ZoneEditor({ zone, onUpdate, onRemove }: ZoneEditorProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border rounded-lg p-2 mb-2 bg-white">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span
            className="w-4 h-4 rounded"
            style={{ backgroundColor: getZoneColor(zone.land_use) }}
          />
          <span className="font-medium">{zone.zone_id}</span>
          <span className="text-sm text-gray-600">
            {ZONE_TYPE_NAMES[zone.land_use] || zone.land_use}
          </span>
          <span className="text-xs bg-gray-100 px-1 rounded">
            {zone.area_ratio * 100}%
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="text-red-500 hover:text-red-700 text-sm"
          >
            删除
          </button>
          <span className="text-gray-400">{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {expanded && (
        <div className="mt-2 pl-6 grid grid-cols-2 gap-2 text-sm">
          <div>
            <label className="block text-gray-600 mb-1">用地类型</label>
            <select
              value={zone.land_use}
              onChange={(e) => onUpdate({ land_use: e.target.value as LandUseType })}
              className="w-full border rounded px-2 py-1"
            >
              {Object.entries(ZONE_TYPE_NAMES).map(([key, name]) => (
                <option key={key} value={key}>{name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-gray-600 mb-1">面积比例</label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={zone.area_ratio}
              onChange={(e) => onUpdate({ area_ratio: parseFloat(e.target.value) })}
              className="w-full border rounded px-2 py-1"
            />
          </div>
          <div>
            <label className="block text-gray-600 mb-1">位置偏向</label>
            <select
              value={zone.location_bias.direction}
              onChange={(e) => onUpdate({
                location_bias: { ...zone.location_bias, direction: e.target.value as DirectionBias }
              })}
              className="w-full border rounded px-2 py-1"
            >
              <option value="center">中心</option>
              <option value="north">北</option>
              <option value="south">南</option>
              <option value="east">东</option>
              <option value="west">西</option>
              <option value="edge">边缘</option>
              <option value="northeast">东北</option>
              <option value="northwest">西北</option>
              <option value="southeast">东南</option>
              <option value="southwest">西南</option>
            </select>
          </div>
          <div>
            <label className="block text-gray-600 mb-1">密度</label>
            <select
              value={zone.density}
              onChange={(e) => onUpdate({ density: e.target.value as DensityLevel })}
              className="w-full border rounded px-2 py-1"
            >
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div className="col-span-2">
            <label className="block text-gray-600 mb-1">描述</label>
            <input
              type="text"
              value={zone.description || ''}
              onChange={(e) => onUpdate({ description: e.target.value })}
              className="w-full border rounded px-2 py-1"
              placeholder="分区描述..."
            />
          </div>
        </div>
      )}
    </div>
  );
}

interface FacilityEditorProps {
  facility: FacilityPoint;
  onUpdate: (update: Partial<FacilityPoint>) => void;
  onRemove: () => void;
}

function FacilityEditor({ facility, onUpdate, onRemove }: FacilityEditorProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border rounded-lg p-2 mb-2 bg-white">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span
            className="w-4 h-4 rounded"
            style={{ backgroundColor: FACILITY_STATUS_COLORS[facility.status] || '#808080' }}
          />
          <span className="font-medium">{facility.facility_id}</span>
          <span className="text-sm text-gray-600">{facility.facility_type}</span>
          <span className="text-xs bg-gray-100 px-1 rounded">
            {facility.status === 'existing' ? '现状' :
             facility.status === 'new' ? '新建' :
             facility.status === 'expansion' ? '扩建' : '迁建'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="text-red-500 hover:text-red-700 text-sm"
          >
            删除
          </button>
          <span className="text-gray-400">{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {expanded && (
        <div className="mt-2 pl-6 grid grid-cols-2 gap-2 text-sm">
          <div>
            <label className="block text-gray-600 mb-1">设施类型</label>
            <input
              type="text"
              value={facility.facility_type}
              onChange={(e) => onUpdate({ facility_type: e.target.value })}
              className="w-full border rounded px-2 py-1"
            />
          </div>
          <div>
            <label className="block text-gray-600 mb-1">状态</label>
            <select
              value={facility.status}
              onChange={(e) => onUpdate({ status: e.target.value as FacilityStatus })}
              className="w-full border rounded px-2 py-1"
            >
              <option value="existing">现状保留</option>
              <option value="new">规划新建</option>
              <option value="expansion">规划改扩建</option>
              <option value="relocation">规划迁建</option>
            </select>
          </div>
          <div>
            <label className="block text-gray-600 mb-1">服务半径 (米)</label>
            <input
              type="number"
              min={0}
              step={50}
              value={facility.service_radius}
              onChange={(e) => onUpdate({ service_radius: parseInt(e.target.value) })}
              className="w-full border rounded px-2 py-1"
            />
          </div>
          <div>
            <label className="block text-gray-600 mb-1">优先级</label>
            <select
              value={facility.priority}
              onChange={(e) => onUpdate({ priority: e.target.value as PriorityLevel })}
              className="w-full border rounded px-2 py-1"
            >
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div className="col-span-2">
            <label className="block text-gray-600 mb-1">位置提示</label>
            <input
              type="text"
              value={facility.location_hint}
              onChange={(e) => onUpdate({ location_hint: e.target.value })}
              className="w-full border rounded px-2 py-1"
            />
          </div>
          <div className="col-span-2">
            <label className="block text-gray-600 mb-1">描述</label>
            <input
              type="text"
              value={facility.description || ''}
              onChange={(e) => onUpdate({ description: e.target.value })}
              className="w-full border rounded px-2 py-1"
            />
          </div>
        </div>
      )}
    </div>
  );
}

interface AxisEditorProps {
  axis: DevelopmentAxis;
  onUpdate: (update: Partial<DevelopmentAxis>) => void;
  onRemove: () => void;
}

function AxisEditor({ axis, onUpdate, onRemove }: AxisEditorProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border rounded-lg p-2 mb-2 bg-white">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="w-4 h-4 rounded bg-blue-500" />
          <span className="font-medium">{axis.axis_id}</span>
          <span className="text-sm text-gray-600">
            {axis.axis_type === 'primary' ? '主轴' :
             axis.axis_type === 'secondary' ? '次轴' :
             axis.axis_type === 'corridor' ? '走廊' : '连接'}
          </span>
          <span className="text-xs bg-gray-100 px-1 rounded">
            {axis.direction === 'east-west' ? '东西' :
             axis.direction === 'north-south' ? '南北' :
             axis.direction === 'radial' ? '放射' : '环状'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            className="text-red-500 hover:text-red-700 text-sm"
          >
            删除
          </button>
          <span className="text-gray-400">{expanded ? '▼' : '▶'}</span>
        </div>
      </div>

      {expanded && (
        <div className="mt-2 pl-6 grid grid-cols-2 gap-2 text-sm">
          <div>
            <label className="block text-gray-600 mb-1">轴线类型</label>
            <select
              value={axis.axis_type}
              onChange={(e) => onUpdate({ axis_type: e.target.value as AxisType })}
              className="w-full border rounded px-2 py-1"
            >
              <option value="primary">主要轴线</option>
              <option value="secondary">次要轴线</option>
              <option value="corridor">发展走廊</option>
              <option value="connector">连接线</option>
            </select>
          </div>
          <div>
            <label className="block text-gray-600 mb-1">方向</label>
            <select
              value={axis.direction}
              onChange={(e) => onUpdate({ direction: e.target.value as AxisDirection })}
              className="w-full border rounded px-2 py-1"
            >
              <option value="east-west">东西向</option>
              <option value="north-south">南北向</option>
              <option value="radial">放射状</option>
              <option value="ring">环状</option>
            </select>
          </div>
          <div className="col-span-2">
            <label className="block text-gray-600 mb-1">参考要素</label>
            <input
              type="text"
              value={axis.reference_feature || ''}
              onChange={(e) => onUpdate({ reference_feature: e.target.value })}
              className="w-full border rounded px-2 py-1"
              placeholder="如：Y122乡道"
            />
          </div>
          <div className="col-span-2">
            <label className="block text-gray-600 mb-1">描述</label>
            <input
              type="text"
              value={axis.description || ''}
              onChange={(e) => onUpdate({ description: e.target.value })}
              className="w-full border rounded px-2 py-1"
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================
// Main Component
// ============================================

interface PlanningSchemeEditorProps {
  scheme: VillagePlanningScheme;
  onSchemeChange: (scheme: VillagePlanningScheme) => void;
  onExport?: () => void;
  onImport?: (json: string) => boolean;
}

export default function PlanningSchemeEditor({
  scheme,
  onSchemeChange,
  onExport,
  onImport,
}: PlanningSchemeEditorProps) {
  const [sectionsExpanded, setSectionsExpanded] = useState({
    zones: true,
    facilities: false,
    axes: false,
  });

  const [jsonInput, setJsonInput] = useState('');
  const [showJsonModal, setShowJsonModal] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const toggleSection = (section: 'zones' | 'facilities' | 'axes') => {
    setSectionsExpanded(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const handleUpdateZone = (zoneId: string, update: Partial<PlanningZone>) => {
    onSchemeChange({
      ...scheme,
      zones: scheme.zones.map(z => z.zone_id === zoneId ? { ...z, ...update } : z),
    });
  };

  const handleRemoveZone = (zoneId: string) => {
    onSchemeChange({
      ...scheme,
      zones: scheme.zones.filter(z => z.zone_id !== zoneId),
    });
  };

  const handleAddZone = () => {
    const newId = `Z${String(scheme.zones.length + 1).padStart(2, '0')}`;
    const newZone: PlanningZone = {
      zone_id: newId,
      land_use: 'residential',
      area_ratio: 0.1,
      location_bias: { direction: 'center' },
      density: 'medium',
      description: '',
    };
    onSchemeChange({ ...scheme, zones: [...scheme.zones, newZone] });
  };

  const handleUpdateFacility = (facilityId: string, update: Partial<FacilityPoint>) => {
    onSchemeChange({
      ...scheme,
      facilities: scheme.facilities.map(f =>
        f.facility_id === facilityId ? { ...f, ...update } : f
      ),
    });
  };

  const handleRemoveFacility = (facilityId: string) => {
    onSchemeChange({
      ...scheme,
      facilities: scheme.facilities.filter(f => f.facility_id !== facilityId),
    });
  };

  const handleAddFacility = () => {
    const newId = `F${String(scheme.facilities.length + 1).padStart(2, '0')}`;
    const newFacility: FacilityPoint = {
      facility_id: newId,
      facility_type: '公共服务设施',
      status: 'new',
      location_hint: '村庄中心',
      service_radius: 300,
      priority: 'medium',
      description: '',
    };
    onSchemeChange({ ...scheme, facilities: [...scheme.facilities, newFacility] });
  };

  const handleUpdateAxis = (axisId: string, update: Partial<DevelopmentAxis>) => {
    onSchemeChange({
      ...scheme,
      axes: scheme.axes.map(a => a.axis_id === axisId ? { ...a, ...update } : a),
    });
  };

  const handleRemoveAxis = (axisId: string) => {
    onSchemeChange({
      ...scheme,
      axes: scheme.axes.filter(a => a.axis_id !== axisId),
    });
  };

  const handleAddAxis = () => {
    const newId = `A${String(scheme.axes.length + 1).padStart(2, '0')}`;
    const newAxis: DevelopmentAxis = {
      axis_id: newId,
      axis_type: 'secondary',
      direction: 'east-west',
      description: '',
    };
    onSchemeChange({ ...scheme, axes: [...scheme.axes, newAxis] });
  };

  const handleFileImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const json = event.target?.result as string;
      if (onImport && onImport(json)) {
        setShowJsonModal(false);
        setJsonInput('');
      }
    };
    reader.readAsText(file);
  };

  const handleJsonImport = () => {
    if (onImport && onImport(jsonInput)) {
      setShowJsonModal(false);
      setJsonInput('');
    }
  };

  return (
    <div className="bg-gray-50 rounded-lg p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-800">规划方案编辑器</h3>
        <div className="flex gap-2">
          <button
            onClick={() => setShowJsonModal(true)}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            JSON 导入
          </button>
          <button
            onClick={onExport}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            JSON 导出
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="text-xs text-gray-600 mb-3 flex gap-3">
        <span>分区: {scheme.zones.length}</span>
        <span>设施: {scheme.facilities.length}</span>
        <span>轴线: {scheme.axes.length}</span>
        <span>总面积: {scheme.total_area_km2 || 0} km²</span>
      </div>

      {/* Zones Section */}
      <div className="mb-3">
        <div
          className="flex items-center justify-between cursor-pointer py-1 bg-yellow-50 rounded px-2"
          onClick={() => toggleSection('zones')}
        >
          <span className="font-medium text-yellow-800">用地分区 ({scheme.zones.length})</span>
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); handleAddZone(); }}
              className="text-xs text-green-600 hover:text-green-800"
            >
              + 添加
            </button>
            <span className="text-gray-400">{sectionsExpanded.zones ? '▼' : '▶'}</span>
          </div>
        </div>
        {sectionsExpanded.zones && (
          <div className="mt-2 max-h-64 overflow-y-auto">
            {scheme.zones.map(zone => (
              <ZoneEditor
                key={zone.zone_id}
                zone={zone}
                onUpdate={(update) => handleUpdateZone(zone.zone_id, update)}
                onRemove={() => handleRemoveZone(zone.zone_id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Facilities Section */}
      <div className="mb-3">
        <div
          className="flex items-center justify-between cursor-pointer py-1 bg-blue-50 rounded px-2"
          onClick={() => toggleSection('facilities')}
        >
          <span className="font-medium text-blue-800">公共设施 ({scheme.facilities.length})</span>
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); handleAddFacility(); }}
              className="text-xs text-green-600 hover:text-green-800"
            >
              + 添加
            </button>
            <span className="text-gray-400">{sectionsExpanded.facilities ? '▼' : '▶'}</span>
          </div>
        </div>
        {sectionsExpanded.facilities && (
          <div className="mt-2 max-h-64 overflow-y-auto">
            {scheme.facilities.map(facility => (
              <FacilityEditor
                key={facility.facility_id}
                facility={facility}
                onUpdate={(update) => handleUpdateFacility(facility.facility_id, update)}
                onRemove={() => handleRemoveFacility(facility.facility_id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Axes Section */}
      <div>
        <div
          className="flex items-center justify-between cursor-pointer py-1 bg-purple-50 rounded px-2"
          onClick={() => toggleSection('axes')}
        >
          <span className="font-medium text-purple-800">发展轴线 ({scheme.axes.length})</span>
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); handleAddAxis(); }}
              className="text-xs text-green-600 hover:text-green-800"
            >
              + 添加
            </button>
            <span className="text-gray-400">{sectionsExpanded.axes ? '▼' : '▶'}</span>
          </div>
        </div>
        {sectionsExpanded.axes && (
          <div className="mt-2 max-h-64 overflow-y-auto">
            {scheme.axes.map(axis => (
              <AxisEditor
                key={axis.axis_id}
                axis={axis}
                onUpdate={(update) => handleUpdateAxis(axis.axis_id, update)}
                onRemove={() => handleRemoveAxis(axis.axis_id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* JSON Import Modal */}
      {showJsonModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-4 max-w-lg w-full mx-4">
            <h4 className="font-semibold mb-3">导入规划方案 JSON</h4>
            <textarea
              value={jsonInput}
              onChange={(e) => setJsonInput(e.target.value)}
              className="w-full border rounded p-2 h-32 text-sm font-mono"
              placeholder='粘贴 JSON 或使用文件上传...'
            />
            <div className="mt-3 flex gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".json"
                onChange={handleFileImport}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-3 py-1 bg-gray-200 rounded hover:bg-gray-300 text-sm"
              >
                选择文件
              </button>
              <button
                onClick={handleJsonImport}
                className="px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 text-sm"
              >
                导入
              </button>
              <button
                onClick={() => setShowJsonModal(false)}
                className="px-3 py-1 bg-gray-200 rounded hover:bg-gray-300 text-sm"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}