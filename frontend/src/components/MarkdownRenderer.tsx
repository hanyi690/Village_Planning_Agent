'use client';

import React from 'react';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  suppressFirstHeader?: boolean;
}

const BLOCK_ELEMENTS = ['<h1', '<h2', '<h3', '<h4', '<ul', '<ol', '<pre', '<blockquote'] as const;

/**
 * Simple Markdown Renderer
 * Converts markdown to HTML without external dependencies
 */
export default function MarkdownRenderer({
  content,
  className = '',
  suppressFirstHeader = false
}: MarkdownRendererProps) {
  const renderMarkdown = (markdown: string): string => {
    if (!markdown) return '';

    let html = markdown;

    // Remove first header if suppressFirstHeader is enabled
    if (suppressFirstHeader) {
      html = html.replace(/^#\s+.*$\n?/m, '');
      html = html.replace(/^##\s+.*$\n?/m, '');
    }

    // Escape HTML tags to prevent XSS
    html = html.replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // Code blocks (must be before other processing)
    html = html.replace(/```(\w+)?\n([\s\S]*?)```/gim, '<pre><code>$2</code></pre>');
    html = html.replace(/`([^`]+)`/gim, '<code>$1</code>');

    // Headers
    html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>\n');
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>\n');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>\n');
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>\n');

    // Bold and Italic
    html = html.replace(/\*\*\*(.*?)\*\*\*/gim, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/gim, '<em>$1</em>');
    html = html.replace(/___(.*?)___/gim, '<strong><em>$1</em></strong>');
    html = html.replace(/__(.*?)__/gim, '<strong>$1</strong>');
    html = html.replace(/_(.*?)_/gim, '<em>$1</em>');

    // Strikethrough
    html = html.replace(/~~(.*?)~~/gim, '<del>$1</del>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/gim, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // Images
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/gim, '<img src="$2" alt="$1" style="max-width: 100%;" />');

    // Unordered lists
    html = html.replace(/^\* (.*$)/gim, '<li>$1</li>');
    html = html.replace(/^- (.*$)/gim, '<li>$1</li>');

    // Ordered lists
    html = html.replace(/^\d+\. (.*$)/gim, '<li>$1</li>');

    // Wrap consecutive list items in <ul> tags
    const listRegex = /(<li>.*<\/li>\n?)+/g;
    html = html.replace(listRegex, (match) => '<ul>' + match + '</ul>');

    // Line breaks and paragraphs
    html = html.replace(/\n\n+/g, '</p>\n<p>');
    html = html.replace(/\n/g, '<br />\n');

    // Wrap in paragraph if not starting with block element
    const startsWithBlock = BLOCK_ELEMENTS.some(tag => html.trim().startsWith(tag));

    if (!startsWithBlock) {
      html = '<p>' + html + '</p>';
    }

    // Clean up empty paragraphs and fix nesting
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>(<h[1-4]>)/g, '$1');
    html = html.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<\/p>/g, '$1');
    html = html.replace(/<p>(<ul>)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');

    return html;
  };

  return (
    <div
      className={`markdown-content ${className}`}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
      style={{
        lineHeight: '1.7',
        color: '#666',
        fontSize: '0.95rem',
        maxHeight: 'none',
        height: 'auto',
        overflow: 'visible'
      }}
    />
  );
}
