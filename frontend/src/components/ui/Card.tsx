'use client';

import { ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  variant?: 'default' | 'elevated' | 'bordered';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

/**
 * Card - 可复用的卡片组件
 *
 * 变体:
 * - default: bg-white rounded-xl border border-gray-100
 * - elevated: bg-white rounded-xl shadow-md
 * - bordered: bg-white rounded-xl border-2 border-gray-200
 *
 * 内边距:
 * - none: p-0
 * - sm: p-4
 * - md: p-6
 * - lg: p-8
 */
export default function Card({
  children,
  className = '',
  variant = 'default',
  padding = 'md',
}: CardProps) {
  const variantStyles = {
    default: 'bg-white rounded-xl border border-gray-100 shadow-sm',
    elevated: 'bg-white rounded-xl shadow-md border-0',
    bordered: 'bg-white rounded-xl border-2 border-gray-200',
  };

  const paddingStyles = {
    none: '',
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8',
  };

  return (
    <div className={`
      ${variantStyles[variant]}
      ${paddingStyles[padding]}
      ${className}
    `}>
      {children}
    </div>
  );
}
