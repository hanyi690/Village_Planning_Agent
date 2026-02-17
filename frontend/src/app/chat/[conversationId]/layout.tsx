/**
 * Chat Route Layout
 * 对话路由布局 - 设置 metadata
 */

import { Metadata } from 'next';

export const metadata: Metadata = {
  title: '对话式规划 | Village Planning Agent',
  description: '通过自然语言对话创建村庄规划方案',
};

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
