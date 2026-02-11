'use client';

/**
 * ActionButtonGroup Component
 * Reusable action button group for messages
 */

import React from 'react';
import { ActionButton } from '@/types/message';
import { getButtonClasses, getActionIconClass } from '@/lib/utils';

interface ActionButtonGroupProps {
  actions: ActionButton[];
  onAction?: (action: ActionButton) => void;
  className?: string;
}

export default function ActionButtonGroup({
  actions,
  onAction,
  className = '',
}: ActionButtonGroupProps) {
  if (!actions || actions.length === 0) return null;

  return (
    <div className={`flex gap-2 flex-wrap ${className}`}>
      {actions.map((action) => (
        <button
          key={action.id}
          className={getButtonClasses(
            action.variant === 'primary' ? 'primary' :
            action.variant === 'success' ? 'success' : 'secondary',
            'md',
            'lg'
          )}
          onClick={() => onAction?.(action)}
        >
          <i className={`fas ${getActionIconClass(action.id)} mr-1.5`} />
          {action.label}
        </button>
      ))}
    </div>
  );
}
