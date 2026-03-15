'use client';

import React from 'react';

interface SegmentedControlProps {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

/**
 * SegmentedControl - iOS/macOS style segmented control for layer navigation
 *
 * Visual design:
 * - Container: bg-gray-100 rounded-xl p-1
 * - Buttons: px-6 py-2 rounded-lg with active/inactive states
 * - Active: bg-white text-blue-600 shadow-sm
 * - Inactive: text-gray-500 hover:text-gray-700
 */
const SegmentedControl: React.FC<SegmentedControlProps> = ({
  options,
  value,
  onChange,
  className = '',
}) => {
  return (
    <div role="tablist" className={`flex p-1 bg-gray-100 rounded-xl w-fit mx-auto ${className}`}>
      {options.map((option) => {
        const isActive = value === option;

        return (
          <button
            key={option}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(option)}
            className={`
              px-6 py-2 text-sm font-medium rounded-lg
              transition-all duration-200
              ${isActive ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-600 hover:text-gray-800'}
            `}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
};

export default SegmentedControl;
