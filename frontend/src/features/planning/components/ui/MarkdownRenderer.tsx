'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import 'katex/dist/katex.min.css';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  suppressFirstHeader?: boolean;
}

/**
 * Preprocess HTML tables to convert math syntax for rehype-katex
 * Converts $...$ to <span class="math-inline">...</span>
 * Converts $$...$$ to <div class="math-display">...</div>
 */
function preprocessMathInHtml(content: string): string {
  // Process display math first ($$...$$) to avoid conflicts with inline math
  let result = content.replace(
    /\$\$([\s\S]*?)\$\$/g,
    '<div class="math-display">$1</div>'
  );
  // Then process inline math ($...$)
  result = result.replace(
    /\$([^\$\n]+?)\$/g,
    '<span class="math-inline">$1</span>'
  );
  return result;
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
    if (!content) return '';

    let result = content;

    // Preprocess math in HTML tables
    result = preprocessMathInHtml(result);

    if (suppressFirstHeader) {
      // Remove first header (level 1 or 2)
      result = result.replace(/^#\s+.*$\n?/m, '');
      result = result.replace(/^##\s+.*$\n?/m, '');
    }

    return result;
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
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeRaw, rehypeKatex]}
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
