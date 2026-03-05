'use client';

/**
 * DimensionSelector - 维度选择器组件
 *
 * 简化版：单列列表，完整显示维度名称
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
      {/* 触发按钮 - 紧凑样式 */}
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={`
          inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full border transition-colors
          ${disabled 
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed border-gray-200' 
            : isOpen 
              ? 'bg-emerald-50 border-emerald-300 text-emerald-700'
              : 'bg-white border-gray-200 text-gray-600 hover:border-emerald-300 hover:bg-emerald-50/50'
          }
        `}
      >
        <span>🎯</span>
        
        {selectedDimensions.length === 0 ? (
          <span>选择维度（可选）</span>
        ) : (
          <>
            <span>已选 {selectedDimensions.length} 项</span>
            <span
              onClick={clearAll}
              className="ml-1 hover:bg-gray-200 rounded-full p-0.5"
            >
              <FontAwesomeIcon icon={faTimes} className="text-[10px]" />
            </span>
          </>
        )}
        
        <FontAwesomeIcon 
          icon={faChevronDown} 
          className={`text-[10px] transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {/* 下拉面板 - 单列列表 - 向上展开 */}
      {isOpen && !disabled && (
        <div className="absolute z-50 bottom-full mb-1 w-96 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
          {/* 头部 */}
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
            <span className="text-sm font-medium text-gray-700">
              选择需要修复的维度
            </span>
            <span className="text-xs text-gray-400">
              {selectedDimensions.length}/{dimensions.length}
            </span>
          </div>

          {/* 维度列表 - 单列 */}
          <div className="max-h-72 overflow-y-auto">
            {dimensions.map(({ key, name, icon }) => {
              const isSelected = selectedDimensions.includes(key);
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleDimension(key)}
                  className={`
                    w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors
                    ${isSelected 
                      ? 'bg-emerald-50 text-emerald-700' 
                      : 'text-gray-700 hover:bg-gray-50'
                    }
                  `}
                >
                  {/* 复选框 */}
                  <span className={`
                    w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0 text-xs
                    ${isSelected 
                      ? 'bg-emerald-500 text-white' 
                      : 'border-2 border-gray-300'
                    }
                  `}>
                    {isSelected && <FontAwesomeIcon icon={faCheck} />}
                  </span>
                  
                  {/* 图标 */}
                  <span className="text-lg flex-shrink-0">{icon}</span>
                  
                  {/* 名称 - 完整显示 */}
                  <span className="flex-1">{name}</span>
                </button>
              );
            })}
          </div>

          {/* 底部提示 */}
          <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
            <p className="text-xs text-gray-500">
              💡 不选择则系统根据反馈内容自动识别相关维度
            </p>
          </div>
        </div>
      )}

      {/* 已选择的维度标签 */}
      {selectedDimensions.length > 0 && !isOpen && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {selectedDimensions.map(key => (
            <span
              key={key}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 text-emerald-700 text-xs rounded-full border border-emerald-200"
            >
              <span>{getDimensionIcon(key)}</span>
              <span>{getDimensionName(key)}</span>
              <button
                type="button"
                onClick={() => onChange(selectedDimensions.filter(d => d !== key))}
                className="hover:bg-emerald-100 rounded-full p-0.5"
              >
                <FontAwesomeIcon icon={faTimes} className="text-[10px]" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
