'use client';

import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function StageReportPanel({ sessionId }: { sessionId: string | null }) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/sessions/${sessionId}/stage-report.md`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((text) => { if (!cancelled) setMarkdown(text); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [sessionId]);

  if (error) return <div className="text-xs text-red-500">阶段报告加载失败: {error}</div>;
  if (markdown === null) return <div className="text-xs text-gray-400">加载阶段报告…</div>;
  return (
    <details>
      <summary className="cursor-pointer select-none text-xs font-medium text-gray-700 py-1">查看阶段报告（Markdown）</summary>
      <div className="mt-1 max-h-96 overflow-auto border border-gray-200 rounded p-3 text-xs">
        <ReactMarkdown>{markdown}</ReactMarkdown>
      </div>
    </details>
  );
}
