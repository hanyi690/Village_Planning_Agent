import { readFile } from 'node:fs/promises';
import path from 'node:path';

let cachedResult: Promise<string> | null = null;

function loadCompleteResult(): Promise<string> {
  if (!cachedResult) {
    const resultPath = path.resolve(
      process.cwd(),
      '..',
      'output',
      'gis',
      'jintian-complete-road-plan',
      'frontend_layers.json',
    );
    cachedResult = readFile(resultPath, 'utf8')
      // The source file is human-readable and almost 29 MB. Compacting it once
      // cuts the transfer to roughly one third and keeps subsequent requests in
      // memory, independent of the Python planning worker on port 8000.
      .then((source) => JSON.stringify(JSON.parse(source)))
      .catch((error) => {
        cachedResult = null;
        throw error;
      });
  }
  return cachedResult;
}

export async function GET() {
  try {
    const body = await loadCompleteResult();
    return new Response(body, {
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=3600, stale-while-revalidate=86400',
      },
    });
  } catch (error) {
    return Response.json(
      {
        detail: '完整 GIS 成果文件不存在或无法读取。',
        reason: error instanceof Error ? error.message : String(error),
      },
      { status: 503 },
    );
  }
}
