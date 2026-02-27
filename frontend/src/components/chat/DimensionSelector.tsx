'use client';

/**
 * DimensionSelector - 维度选择器组件
 *
 * 用于审查时选择需要修复的具体维度
 * 支持多选，不选择则后端自动识别
 */

import { useState, useRef, useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronDown, faTimes, faCheck } from '@fortawesome/free-solid-svg-icons';
import { getDimensionConfigsByLayer, getDimensionIcon, getDimensionName } from '@/config/dimensions';

interface DimensionSelectorProps {
  layer: number;
  selectedDimensions: string[];
  onChange: (dimensions: string[]) => void;
  disabled?: boolean;
}

export default function DimensionSelector({
  layer,
  selectedDimensions,
  onChange,
  disabled = false,
}: DimensionSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 获取当前层级的维度配置
  const dimensions = getDimensionConfigsByLayer(layer);

  // 点击外部关闭下拉
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // 切换维度选择
  const toggleDimension = (key: string) => {
    if (selectedDimensions.includes(key)) {
      onChange(selectedDimensions.filter(d => d !== key));
    } else {
      onChange([...selectedDimensions, key]);
    }
  };

  // 清除所有选择
  const clearAll = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange([]);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* 触发按钮 */}
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={`
          flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors
          ${disabled 
            ? 'bg-gray-100 text-gray-600 cursor-not-allowed border-gray-200' 
            : isOpen 
              ? 'bg-blue-50 border-blue-300 text-blue-700'
              : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
          }
        `}
      >
        <span className="text-gray-600">🎯</span>
        
        {selectedDimensions.length === 0 ? (
          <span className="text-gray-600">选择维度（可选，不选自动识别）</span>
        ) : (
          <span className="text-gray-700">
            已选 {selectedDimensions.length} 个维度
          </span>
        )}
        
        {selectedDimensions.length > 0 && !disabled && (
          <span
            onClick={clearAll}
            className="ml-1 p-1 hover:bg-gray-200 rounded"
          >
            <FontAwesomeIcon icon={faTimes} className="text-xs text-gray-600" />
          </span>
        )}
        
        <FontAwesomeIcon 
          icon={faChevronDown} 
          className={`text-xs text-gray-600 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {/* 下拉面板 */}
      {isOpen && !disabled && (
        <div className="absolute z-50 mt-1 w-80 bg-white border border-gray-200 rounded-lg shadow-lg max-h-80 overflow-y-auto">
          {/* 头部 */}
          <div className="sticky top-0 bg-gray-50 px-3 py-2 border-b border-gray-200 flex justify-between items-center">
            <span className="text-sm font-medium text-gray-700">
              选择需要修复的维度
            </span>
            <span className="text-xs text-gray-600">
              {selectedDimensions.length}/{dimensions.length}
            </span>
          </div>

          {/* 维度列表 */}
          <div className="p-1">
            {dimensions.map(({ key, name, icon }) => {
              const isSelected = selectedDimensions.includes(key);
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleDimension(key)}
                  className={`
                    w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-colors
                    ${isSelected 
                      ? 'bg-blue-50 text-blue-700' 
                      : 'text-gray-700 hover:bg-gray-50'
                    }
                  `}
                >
                  {/* 复选框 */}
                  <span className={`
                    w-5 h-5 rounded border flex items-center justify-center flex-shrink-0
                    ${isSelected 
                      ? 'bg-blue-100 border-blue-300 text-blue-700' 
                      : 'border-gray-300'
                    }
                  `}>
                    {isSelected && <FontAwesomeIcon icon={faCheck} className="text-xs" />}
                  </span>
                  
                  {/* 图标 */}
                  <span className="text-lg">{icon}</span>
                  
                  {/* 名称 */}
                  <span className="text-sm flex-1">{name}</span>
                  
                  {/* 键名 */}
                  <span className="text-xs text-gray-600">{key}</span>
                </button>
              );
            })}
          </div>

          {/* 底部提示 */}
          <div className="sticky bottom-0 bg-gray-50 px-3 py-2 border-t border-gray-200">
            <p className="text-xs text-gray-600">
              💡 不选择则系统根据反馈内容自动识别相关维度
            </p>
          </div>
        </div>
      )}

      {/* 已选择的维度标签 */}
      {selectedDimensions.length > 0 && !isOpen && (
        <div className="flex flex-wrap gap-1 mt-2">
          {selectedDimensions.map(key => (
            <span
              key={key}
              className="inline-flex items-center gap-1 px-2 py-1 bg-blue-50 text-blue-700 text-xs rounded-full"
            >
              <span>{getDimensionIcon(key)}</span>
              <span>{getDimensionName(key)}</span>
              <button
                type="button"
                onClick={() => onChange(selectedDimensions.filter(d => d !== key))}
                className="ml-1 hover:bg-blue-100 rounded-full p-0.5"
              >
                <FontAwesomeIcon icon={faTimes} className="text-xs" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
