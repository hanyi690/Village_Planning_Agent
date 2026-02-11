'use client';

/**
 * CodeBlock Component
 * 代码块组件 - 带语法高亮和复制功能
 */

import React, { useState } from 'react';

export interface CodeBlockProps {
  code: string;
  language?: string;
  filename?: string;
  lineNumbers?: boolean;
  collapsible?: boolean;
  maxHeight?: string;
  theme?: 'light' | 'dark';
  className?: string;
}

/**
 * 代码块组件
 *
 * @example
 * <CodeBlock
 *   code="console.log('Hello, world!');"
 *   language="javascript"
 *   filename="example.js"
 *   lineNumbers
 *   collapsible
 * />
 */
export default function CodeBlock({
  code,
  language = 'text',
  filename,
  lineNumbers = false,
  collapsible = false,
  maxHeight = '400px',
  theme = 'light',
  className = '',
}: CodeBlockProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy code:', error);
    }
  };

  const lines = code.split('\n');
  const shouldShowCollapseButton = collapsible && lines.length > 10;

  // 简单的语法高亮（TODO: 替换为 Prism.js 或 Shiki）
  const highlightCode = (code: string, lang: string): string => {
    // 这里只是一个示例，实际应该使用专业的语法高亮库
    return code;
  };

  const highlightedCode = highlightCode(code, language);

  return (
    <div
      className={`code-block ${className}`}
      style={{
        position: 'relative',
        margin: '1rem 0',
        borderRadius: '8px',
        overflow: 'hidden',
        backgroundColor: theme === 'dark' ? '#1e1e1e' : '#f6f8fa',
        border: `1px solid ${theme === 'dark' ? '#333' : '#e1e4e8'}`,
        fontFamily: "'Fira Code', 'Consolas', 'Monaco', monospace",
        fontSize: '13px',
        lineHeight: '1.6',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.5rem 1rem',
          backgroundColor: theme === 'dark' ? '#2d2d2d' : '#e1e4e8',
          borderBottom: `1px solid ${theme === 'dark' ? '#333' : '#e1e4e8'}`,
        }}
      >
        {/* Language / Filename */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <i
            className={`fas ${
              language === 'javascript' || language === 'js'
                ? 'fa-js'
                : language === 'typescript' || language === 'ts'
                ? 'fa-code'
                : language === 'python'
                ? 'fa-python'
                : language === 'java'
                ? 'fa-java'
                : 'fa-file-code'
            }`}
            style={{
              fontSize: '14px',
              color: theme === 'dark' ? 'var(--text-cream-ivory)' : '#666',
            }}
          />
          <span
            style={{
              fontSize: '12px',
              fontWeight: '600',
              color: theme === 'dark' ? 'var(--text-cream-ivory)' : '#333',
            }}
          >
            {filename || language.toUpperCase()}
          </span>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {/* Collapse Button */}
          {shouldShowCollapseButton && (
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              style={{
                padding: '4px 8px',
                fontSize: '11px',
                fontWeight: '500',
                color: theme === 'dark' ? 'var(--text-cream-ivory)' : '#666',
                backgroundColor: 'transparent',
                border: '1px solid transparent',
                borderRadius: '4px',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor =
                  theme === 'dark' ? '#444' : '#ddd';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
              title={isCollapsed ? '展开代码' : '折叠代码'}
            >
              <i
                className={`fas ${isCollapsed ? 'fa-chevron-down' : 'fa-chevron-up'}`}
              />
            </button>
          )}

          {/* Copy Button */}
          <button
            onClick={handleCopy}
            style={{
              padding: '4px 8px',
              fontSize: '11px',
              fontWeight: '500',
              color: theme === 'dark' ? 'var(--text-cream-ivory)' : '#666',
              backgroundColor: 'transparent',
              border: '1px solid transparent',
              borderRadius: '4px',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor =
                theme === 'dark' ? '#444' : '#ddd';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <i
              className={`fas ${isCopied ? 'fa-check' : 'fa-copy'}`}
              style={{ color: isCopied ? '#10b981' : undefined }}
            />
          </button>
        </div>
      </div>

      {/* Code Content */}
      <div
        style={{
          overflow: isCollapsed ? 'hidden' : 'auto',
          maxHeight: isCollapsed ? '0' : maxHeight,
          transition: 'max-height 0.3s ease',
          position: 'relative',
        }}
      >
        <pre
          style={{
            margin: 0,
            padding: '1rem',
            overflow: 'auto',
            display: 'flex',
          }}
        >
          {/* Line Numbers */}
          {lineNumbers && (
            <div
              style={{
                padding: '0 0.75rem 0 0',
                marginRight: '0.75rem',
                borderRight: `1px solid ${theme === 'dark' ? '#444' : '#ddd'}`,
                color: theme === 'dark' ? '#888' : '#999',
                userSelect: 'none',
                textAlign: 'right',
                minWidth: '2.5rem',
              }}
            >
              {lines.map((_, i) => (
                <div
                  key={i}
                  style={{
                    lineHeight: '1.6',
                    fontSize: '13px',
                  }}
                >
                  {i + 1}
                </div>
              ))}
            </div>
          )}

          {/* Code */}
          <code
            style={{
              flex: 1,
              color: theme === 'dark' ? '#d4d4d4' : '#24292e',
              whiteSpace: 'pre',
              fontFamily: 'inherit',
            }}
          >
            {highlightedCode}
          </code>
        </pre>
      </div>

      {/* Collapse Indicator */}
      {isCollapsed && (
        <div
          style={{
            padding: '0.5rem',
            textAlign: 'center',
            fontSize: '11px',
            color: theme === 'dark' ? '#888' : '#666',
            backgroundColor: theme === 'dark' ? '#2d2d2d' : '#f6f8fa',
            cursor: 'pointer',
          }}
          onClick={() => setIsCollapsed(false)}
        >
          <i className="fas fa-chevron-up" /> 展开代码 ({lines.length} 行)
        </div>
      )}
    </div>
  );
}

/**
 * Inline Code Component
 */
export function InlineCode({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <code
      className={`inline-code ${className}`}
      style={{
        padding: '0.2em 0.4em',
        margin: '0',
        fontSize: '85%',
        backgroundColor: 'rgba(175, 184, 193, 0.2)',
        borderRadius: '6px',
        fontFamily: "'Fira Code', 'Consolas', 'Monaco', monospace",
        color: '#24292e',
        wordWrap: 'break-word',
      }}
    >
      {children}
    </code>
  );
}
