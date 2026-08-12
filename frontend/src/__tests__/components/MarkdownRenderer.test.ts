import { normalizeTableCaptions } from '@/features/planning/utils/markdown-table-captions';

describe('normalizeTableCaptions', () => {
  it('moves a historical caption row above its table', () => {
    const source = [
      '| 地类 | 现状（公顷） | 规划（公顷） |',
      '| :--- | :--- | :--- |',
      '| 耕地 | 85.20 | 85.20 |',
      '| 表 3-1 土地利用结构调整表 | | |',
    ].join('\n');

    const result = normalizeTableCaptions(source);

    expect(result.indexOf('class="table-caption"')).toBeLessThan(result.indexOf('| 地类'));
    expect(result).not.toContain('| 表 3-1 土地利用结构调整表 |');
  });

  it('keeps a new caption above the table without duplicating it', () => {
    const source = [
      '表 3-1 土地利用结构调整表',
      '',
      '| 地类 | 面积 |',
      '| :--- | :--- |',
      '| 耕地 | 85.20 |',
    ].join('\n');

    const result = normalizeTableCaptions(source);

    expect(result.match(/表 3-1 土地利用结构调整表/g)).toHaveLength(1);
    expect(result.indexOf('class="table-caption"')).toBeLessThan(result.indexOf('| 地类'));
  });

  it('moves a sidebar caption column above its table', () => {
    const source = [
      '| 表 3-16 宅基地规划表 | 项目 | 数量 | 面积（公顷） |',
      '| | 现状宅基地 | 132 处 | 13.20 |',
      '| | 新增宅基地 | 45 处 | 1.35 |',
    ].join('\n');

    const result = normalizeTableCaptions(source);

    expect(result).toContain('class="table-caption"');
    expect(result).toContain('表 3-16 宅基地规划表');
    expect(result).toContain('| 项目 | 数量 | 面积（公顷） |');
    expect(result).not.toContain('| 表 3-16 宅基地规划表 |');
  });
});
