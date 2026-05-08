'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  suppressFirstHeader?: boolean;
}

/**
 * Markdown Renderer
 * Uses react-markdown with remark-gfm plugin for full markdown support including tables
 */
export default function MarkdownRenderer({
  content,
  className = '',
  suppressFirstHeader = false,
}: MarkdownRendererProps) {
  // Process content to remove first header if suppressFirstHeader is enabled
  const processedContent = React.useMemo(() => {
    if (!suppressFirstHeader || !content) return content;

    let html = content;
    // Remove first header (level 1 or 2)
    html = html.replace(/^#\s+.*$\n?/m, '');
    html = html.replace(/^##\s+.*$\n?/m, '');

    return html;
  }, [content, suppressFirstHeader]);

  return (
    <div
      className={`markdown-content ${className}`}
      style={{
        lineHeight: '1.7',
        color: '#666',
        fontSize: '0.95rem',
        maxHeight: 'none',
        height: 'auto',
        overflow: 'visible',
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Customize link rendering to open in new tab
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          // Customize image rendering
          img: ({ src, alt }) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={src}
              alt={alt}
              style={{ maxWidth: '100%', height: 'auto' }}
              className="rounded-lg shadow-sm my-2"
              loading="lazy"
            />
          ),
        }}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  );
}
