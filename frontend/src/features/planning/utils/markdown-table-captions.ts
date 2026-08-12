const TABLE_SEPARATOR_RE = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
const TABLE_CAPTION_RE = /^(?:表|附表)\s*[0-9一二三四五六七八九十]+(?:\s*[-－—.]\s*[0-9一二三四五六七八九十]+)?\s*[\u4e00-\u9fff]/;

function tableCells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
}

function toTableRow(cells: string[]): string {
  return `| ${cells.join(' | ')} |`;
}

function captionText(line: string): string | null {
  const value = line.trim().replace(/^\*{1,2}|\*{1,2}$/g, '').trim();
  return TABLE_CAPTION_RE.test(value) ? value : null;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function isMarkdownTableStart(lines: string[], index: number): boolean {
  if (!lines[index]?.trim().startsWith('|')) return false;
  if (index + 1 >= lines.length) return false;
  const next = lines[index + 1].trim();
  return TABLE_SEPARATOR_RE.test(next) || next.startsWith('|');
}

function peelCaptionFromTableBlock(block: string[]): { caption: string | null; block: string[] } {
  if (block.length === 0) return { caption: null, block };

  const rows = block.map(tableCells);
  const firstRow = rows[0] ?? [];
  const firstCellCaption = captionText(firstRow[0] ?? '');

  if (firstCellCaption) {
    const headerCells = firstRow.slice(1).filter(Boolean);
    if (headerCells.length > 0) {
      const rebuilt: string[] = [toTableRow(headerCells)];
      let startIndex = 1;

      if (block[1] && TABLE_SEPARATOR_RE.test(block[1])) {
        const sepCells = tableCells(block[1]);
        rebuilt.push(toTableRow(sepCells.slice(sepCells.length - headerCells.length)));
        startIndex = 2;
      } else {
        rebuilt.push(toTableRow(headerCells.map(() => ':---')));
      }

      for (let rowIndex = startIndex; rowIndex < block.length; rowIndex += 1) {
        if (TABLE_SEPARATOR_RE.test(block[rowIndex])) continue;
        const normalized = rows[rowIndex].slice(1);
        if (normalized.filter(Boolean).length === 0) continue;
        rebuilt.push(toTableRow(normalized));
      }

      return { caption: firstCellCaption, block: rebuilt };
    }

    if (firstRow.filter(Boolean).length === 1) {
      return { caption: firstCellCaption, block: block.slice(1) };
    }
  }

  const singleCellCaptionRow = rows.find((cells) => {
    const nonEmpty = cells.filter(Boolean);
    return nonEmpty.length === 1 && Boolean(captionText(nonEmpty[0]));
  });
  if (singleCellCaptionRow) {
    const caption = captionText(singleCellCaptionRow.filter(Boolean)[0])!;
    const filtered = block.filter((line) => {
      const nonEmpty = tableCells(line).filter(Boolean);
      return !(nonEmpty.length === 1 && captionText(nonEmpty[0]) === caption);
    });
    return { caption, block: filtered };
  }

  return { caption: null, block };
}

/** Move planning-document captions above their table, including old caption rows. */
export function normalizeTableCaptions(content: string): string {
  const lines = content.split('\n');
  const output: string[] = [];

  for (let i = 0; i < lines.length; i += 1) {
    if (!isMarkdownTableStart(lines, i)) {
      output.push(lines[i]);
      continue;
    }

    const block: string[] = [];
    while (i < lines.length && lines[i].trim().startsWith('|')) {
      block.push(lines[i]);
      i += 1;
    }

    const peeled = peelCaptionFromTableBlock(block);
    let caption = peeled.caption;
    let cleanBlock = peeled.block;

    cleanBlock = cleanBlock.filter((line, index) => {
      if (index < 2) return true;
      const nonEmptyCells = tableCells(line).filter(Boolean);
      const candidate = nonEmptyCells.length === 1 ? captionText(nonEmptyCells[0]) : null;
      if (!caption && candidate) {
        caption = candidate;
        return false;
      }
      return true;
    });

    let previous = output.length - 1;
    while (previous >= 0 && !output[previous].trim()) previous -= 1;
    const previousCaption = previous >= 0 ? captionText(output[previous]) : null;
    if (!caption && previousCaption) {
      caption = previousCaption;
      output.splice(previous, 1);
    }

    const followingCaption = i < lines.length ? captionText(lines[i]) : null;
    if (!caption && followingCaption) {
      caption = followingCaption;
      i += 1;
    }

    if (caption) {
      output.push('', `<div class="table-caption" role="note">${escapeHtml(caption)}</div>`, '');
    }
    output.push(...cleanBlock);
    i -= 1;
  }

  return output.join('\n');
}
