'use client';

import { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronDown, faCheckSquare, faSquare } from '@fortawesome/free-solid-svg-icons';

interface DimensionSelectorProps {
  dimensions?: string[];
  selectedDimensions: string[];
  onChange: (dimensions: string[]) => void;
}

export default function DimensionSelector({
  selectedDimensions = [],
  onChange,
}: DimensionSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);

  const defaultDimensions = [
    { id: 'location', label: '区位交通' },
    { id: 'socio_economic', label: '社会经济' },
    { id: 'villager_wishes', label: '村民意愿' },
    { id: 'superior_planning', label: '上位规划' },
    { id: 'natural_environment', label: '自然环境' },
    { id: 'land_use', label: '土地利用' },
    { id: 'traffic', label: '街巷空间' },
    { id: 'public_services', label: '公共服务' },
    { id: 'infrastructure', label: '基础设施' },
    { id: 'ecological_green', label: '生态绿地' },
    { id: 'architecture', label: '建筑风貌' },
    { id: 'historical_culture', label: '历史文化' },
  ];

  const handleToggle = (dimensionId: string) => {
    const next = selectedDimensions.includes(dimensionId)
      ? selectedDimensions.filter((d) => d !== dimensionId)
      : [...selectedDimensions, dimensionId];
    onChange(next);
  };

  return (
    <div className="relative">
      {/* 更加简约的选择器外观，融入聊天卡片 */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-full hover:bg-white transition-all group"
      >
        <span className="text-xs font-medium text-gray-600 group-hover:text-green-600">
          {selectedDimensions.length === 0 ? '全部分类' : `指定 ${selectedDimensions.length} 个维度`}
        </span>
        <FontAwesomeIcon 
          icon={faChevronDown} 
          className={`text-[10px] text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setIsOpen(false)} />
          <div className="absolute left-0 bottom-full mb-2 z-40 w-64 bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200">
            <div className="p-2 grid grid-cols-2 gap-1 max-h-80 overflow-y-auto">
              {defaultDimensions.map((dim) => {
                const isSelected = selectedDimensions.includes(dim.id);
                return (
                  <button
                    key={dim.id}
                    onClick={() => handleToggle(dim.id)}
                    className={`flex items-center gap-2 px-2 py-2 rounded-lg text-left transition-colors ${
                      isSelected ? 'bg-green-50 text-green-700' : 'hover:bg-gray-50 text-gray-600'
                    }`}
                  >
                    <FontAwesomeIcon 
                      icon={isSelected ? faCheckSquare : faSquare} 
                      className="text-xs" // 强制限制图标大小
                    />
                    <span className="text-[11px] truncate font-medium">{dim.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}