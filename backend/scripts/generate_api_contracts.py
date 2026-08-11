"""Generate committed frontend contract snapshots from canonical Pydantic models."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import v1_router as router
from app.api.v1.contracts import PublicEvent


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    output_dir = project_root / 'docs' / 'contracts'
    output_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title='Village Planning Stable API',
        version='1.0.0',
        openapi_version='3.1.0',
    )
    app.include_router(router)
    (output_dir / 'openapi-v1.json').write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    (output_dir / 'sse-events-v1.schema.json').write_text(
        json.dumps(TypeAdapter(PublicEvent).json_schema(), ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
