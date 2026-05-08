
/**
 * 知识引用组件 - 显示规划依据
 *
 * 功能：
 * - 显示RAG系统检索到的知识来源
 * - 支持查看原文（Phase 1全文上下文）
 * - 可折叠显示，优化UI布局
 */

import React, { useState } from 'react';

interface KnowledgeReference {
  source: string;
  chapter?: string;
  page?: string;
  excerpt?: string;
}

interface KnowledgeReferenceProps {
  references: KnowledgeReference[];
  className?: string;
}

export default function KnowledgeReference({
  references,
  className = '',
}: KnowledgeReferenceProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [viewingOriginal, setViewingOriginal] = useState<string | null>(null);

  if (!references || references.length === 0) {
    return null;
  }

  const handleViewOriginal = async (ref: KnowledgeReference) => {
    setViewingOriginal(ref.source);

    try {
      // 调用API获取原文上下文（Phase 1）
      const response = await fetch('/api/knowledge/context', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          source: ref.source,
          chapter: ref.chapter,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // 显示原文内容（可以使用模态框或侧边栏）
        console.log('Original content:', data.content);
        // TODO: 实现原文显示UI
      } else {
        console.error('Failed to fetch original content');
      }
    } catch (error) {
      console.error('Error fetching original content:', error);
    } finally {
      setViewingOriginal(null);
    }
  };

  return (
    <div
      className={`knowledge-references bg-blue-50 border border-blue-200 rounded-lg p-4 mt-4 ${className}`}
    >
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <svg
            className="w-5 h-5 text-blue-600"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
            />
          </svg>
          <h4 className="text-sm font-bold text-blue-900">规划依据</h4>
          <span className="text-xs text-blue-600 bg-blue-100 px-2 py-0.5 rounded">
            {references.length} 条
          </span>
        </div>
        <svg
          className={`w-5 h-5 text-blue-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {isExpanded && (
        <div className="space-y-2 mt-3">
          {references.map((ref, idx) => (
            <div
              key={idx}
              className="text-sm bg-white p-3 rounded border border-blue-100 hover:shadow-sm transition-shadow"
            >
              <div className="flex items-start gap-2">
                <span className="text-blue-600 font-medium mt-0.5">•</span>
                <div className="flex-1">
                  <div className="font-medium text-gray-900 mb-1">{ref.source}</div>
                  {ref.chapter && (
                    <div className="text-xs text-gray-600 mb-1">
                      章节: {ref.chapter}
                      {ref.page && ` (第${ref.page}页)`}
                    </div>
                  )}
                  {ref.excerpt && (
                    <div className="text-xs text-gray-600 italic bg-gray-50 p-2 rounded">
                      &quot;{ref.excerpt.substring(0, 100)}
                      {ref.excerpt.length > 100 ? '...' : ''}&quot;
                    </div>
                  )}
                </div>
                <button
                  className="text-xs text-blue-600 hover:text-blue-800 underline whitespace-nowrap disabled:opacity-50"
                  onClick={() => handleViewOriginal(ref)}
                  disabled={viewingOriginal === ref.source}
                >
                  {viewingOriginal === ref.source ? '加载中...' : '查看原文'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * 知识引用列表项类型（用于MessageBubble）
 */
export interface KnowledgeReferenceList {
  references: KnowledgeReference[];
  dimension?: string;
  layer?: number;
}
