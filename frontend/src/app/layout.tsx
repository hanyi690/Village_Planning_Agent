import type { Metadata, Viewport } from 'next';
import './globals.css';
import '../styles/layer-report.css';

export const metadata: Metadata = {
  title: '村庄规划智能体',
  description: '基于LangGraph的村庄规划智能系统',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
