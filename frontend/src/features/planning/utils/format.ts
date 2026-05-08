/**
 * Formatting Utilities
 */

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function truncateText(text: string, maxLen: number = 500): string {
  if (text.length <= maxLen) return text;
  const breakPoint = text.lastIndexOf('\n', maxLen);
  if (breakPoint > maxLen * 0.7) return text.slice(0, breakPoint) + '...';
  return text.slice(0, maxLen) + '...';
}