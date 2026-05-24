/**
 * Download utilities for file export.
 */

import type { ExportFormat } from '../api/types';

/**
 * Trigger browser download for a Blob.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Get file extension for export format.
 */
export function getFileExtension(format: ExportFormat): string {
  const extMap: Record<ExportFormat, string> = {
    json: '.json',
    md: '.md',
    docx: '.docx',
    planning_text: '_规划文本.md',
  };
  return extMap[format];
}

/**
 * Get display name for export format.
 */
export function getFormatDisplayName(format: ExportFormat): string {
  const nameMap: Record<ExportFormat, string> = {
    json: 'JSON',
    md: 'Markdown',
    docx: 'Word',
    planning_text: '规划文本',
  };
  return nameMap[format];
}

/**
 * Get display name for export layer.
 */
export function getLayerDisplayName(layer: number): string {
  const nameMap: Record<number, string> = {
    1: 'L1 现状分析',
    2: 'L2 规划思路',
    3: 'L3 详细规划',
  };
  return nameMap[layer] || `Layer ${layer}`;
}