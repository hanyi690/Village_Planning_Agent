export const JINTIAN_DEMO_REPORT_PATH = '/demo/jintian_village.md';

export const JINTIAN_DEMO_METADATA = {
  projectName: '金田村村庄规划（2022—2035年）',
  province: '广东省',
  city: '梅州市',
  county: '平远县',
  township: '泗水镇',
  villageName: '金田村',
  planningPeriod: '2022—2035年',
  constraints:
    '严格保护永久基本农田、生态保护红线和历史文化保护要素；新增道路避让高地质灾害风险区。',
} as const;

export const JINTIAN_DEFAULT_TASK =
  '编制梅州市金田村村庄规划，涵盖国土空间布局、产业发展、人居环境、设施配套、历史文化保护等方面。';

export interface JintianDemoInput {
  villageData: string;
  taskDescription: string;
  constraints: string;
  projectName: string;
  province: string;
  city: string;
  county: string;
  township: string;
  villageName: string;
  planningPeriod: string;
}

export class DemoReportLoadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DemoReportLoadError';
  }
}

export async function loadJintianDemoInput(
  taskDescription = JINTIAN_DEFAULT_TASK,
  fetcher: typeof fetch = fetch,
): Promise<JintianDemoInput> {
  let response: Response;
  try {
    response = await fetcher(JINTIAN_DEMO_REPORT_PATH);
  } catch {
    throw new DemoReportLoadError('完整金田村现状报告加载失败，请检查前端静态资源服务后重试。');
  }

  if (!response.ok) {
    throw new DemoReportLoadError(`完整金田村现状报告加载失败（HTTP ${response.status}），请检查前端静态资源服务后重试。`);
  }

  const villageData = await response.text();
  if (!villageData.trim()) {
    throw new DemoReportLoadError('完整金田村现状报告为空，未填入示例内容。');
  }

  return {
    ...JINTIAN_DEMO_METADATA,
    taskDescription,
    villageData,
  };
}
