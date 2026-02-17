/**
 * Chat Root Layout
 * 对话根布局
 */

import { Metadata } from 'next';

export const metadata: Metadata = {
  title: '对话式规划 | Village Planning Agent',
  description: '通过自然语言对话创建村庄规划方案',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
