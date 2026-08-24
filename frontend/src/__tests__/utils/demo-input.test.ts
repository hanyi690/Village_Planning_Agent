import fs from 'node:fs';
import path from 'node:path';

import {
  JINTIAN_DEMO_REPORT_PATH,
  JINTIAN_DEFAULT_TASK,
  loadJintianDemoInput,
} from '@/features/planning/utils/demo-input';

const normalize = (value: string) => value.replace(/\r\n/g, '\n').trimEnd();

describe('Jintian demo input', () => {
  it('loads the complete report and shared metadata', async () => {
    const report = '# 完整金田村现状报告';
    const fetcher = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => report,
    });

    await expect(loadJintianDemoInput(JINTIAN_DEFAULT_TASK, fetcher)).resolves.toMatchObject({
      villageData: report,
      villageName: '金田村',
      township: '泗水镇',
      taskDescription: JINTIAN_DEFAULT_TASK,
    });
    expect(fetcher).toHaveBeenCalledWith(JINTIAN_DEMO_REPORT_PATH);
  });

  it('surfaces static report failures instead of leaving a partial example', async () => {
    const fetcher = jest.fn().mockResolvedValue({ ok: false, status: 404, text: async () => '' });

    await expect(loadJintianDemoInput(JINTIAN_DEFAULT_TASK, fetcher)).rejects.toThrow('HTTP 404');
  });

  it('keeps the public demo byte content aligned with the original report', () => {
    const publicReport = fs.readFileSync(
      path.resolve(__dirname, '../../../public/demo/jintian_village.md'),
      'utf8',
    );
    const sourceReport = fs.readFileSync(
      path.resolve(__dirname, '../../../../docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md'),
      'utf8',
    );

    expect(normalize(publicReport)).toBe(normalize(sourceReport));
  });

  it('uses the shared loader from both active example entry points', () => {
    const workbench = fs.readFileSync(
      path.resolve(__dirname, '../../features/planning/components/PlanningWorkbenchPage.tsx'),
      'utf8',
    );
    const legacyForm = fs.readFileSync(
      path.resolve(__dirname, '../../features/planning/components/VillageInputForm.tsx'),
      'utf8',
    );

    expect(workbench).toContain("from '@/features/planning/utils/demo-input'");
    expect(workbench).toContain('loadJintianDemoInput(EXAMPLE_TASKS[overviewLevel])');
    expect(workbench).toContain("useState<OverviewLevel>('L3 详细规划')");
    expect(workbench).toContain("setOverviewLevel('L3 详细规划')");
    expect(legacyForm).toContain("from '@/features/planning/utils/demo-input'");
    expect(legacyForm).toContain('loadJintianDemoInput()');
    expect(workbench).not.toContain('setVillageData(`');
    expect(legacyForm).not.toContain("fetch('/demo/jintian_village.md')");
  });
});
