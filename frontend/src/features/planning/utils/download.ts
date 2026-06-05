/**
 * Download utilities for file export.
 */

type LayerFormat = 'json' | 'md' | 'docx';

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
export function getFileExtension(format: LayerFormat): string {
  const extMap: Record<LayerFormat, string> = {
    json: '.json',
    md: '.md',
    docx: '.docx',
  };
  return extMap[format];
}

/**
 * Get display name for export format.
 */
export function getFormatDisplayName(format: LayerFormat): string {
  const nameMap: Record<LayerFormat, string> = {
    json: 'JSON',
    md: 'Markdown',
    docx: 'Word',
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