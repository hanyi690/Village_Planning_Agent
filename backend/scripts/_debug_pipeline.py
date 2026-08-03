"""Debug: 看 catalog enrichment 是不是被调用"""
import sys, os
os.environ['LOG_LEVEL'] = 'DEBUG'
sys.path.insert(0, '.')

import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s %(name)s: %(message)s')

# 重定向 stderr 静音 WMTS
sys.stderr = open(os.devnull, 'w')

from app.modules.data import DataCatalog

catalog = DataCatalog()

# 直接调 _enrich_external_anchors 看 bbox
bundle = catalog.load_village_bundle('金田')
print(f'bbox: {bundle.metadata.bbox_wgs84}')
print(f'province: {bundle.metadata.province!r}')
print(f'city: {bundle.metadata.city!r}')
print(f'county: {bundle.metadata.county!r}')
print(f'township: {bundle.metadata.township!r}')

# 手动调 pipeline
from app.modules.data.catalog.external_anchors import ExternalAnchorPipeline

pipeline = ExternalAnchorPipeline()
cfg = {
    "province": bundle.metadata.province or "广东省",
    "city": bundle.metadata.city or "梅州市",
    "county": bundle.metadata.county or "平远县",
    "adcode": "441426",
}
injected = pipeline.run(bundle, bundle.metadata.bbox_wgs84, cfg)
print(f'injected: {injected}')

pts = bundle.points.get('annotations_current') or []
sources = {}
for f in pts:
    raw = getattr(f, '_raw', None) or {}
    if isinstance(raw, dict):
        src = raw.get('anchor_source', 'local')
    else:
        src = 'local'
    sources[src] = sources.get(src, 0) + 1
print(f'sources after manual call: {sources}')