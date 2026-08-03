import sys, os
os.environ['LOG_LEVEL'] = 'CRITICAL'
sys.path.insert(0, '.')
from app.modules.data import DataCatalog
from app.modules.spatial_ops.geometry import village_boundary_geometry
from app.modules.data.catalog.external_anchors import ExternalAnchorPipeline
from app.modules.data.providers.baidu.provider import BaiduProvider
from app.modules.data.providers.tencent.provider import TencentMapProvider

catalog = DataCatalog()
catalog.set_admin_meta('金田', province='广东省', city='梅州市',
                       county='平远县', township='泗水镇',
                       adcode_12='441426110000')
bundle = catalog.load_village_bundle('金田')

boundary = village_boundary_geometry(bundle)
print('boundary:', boundary is not None)

b = BaiduProvider()
r = b.search_region('村', region='441426110000', region_limit=True, page_size=20)
pois = BaiduProvider._parse_pois((r.data or {}).get('results', []))
print(f'百度: success={r.success}, count={len(pois)}')
if pois:
    p = pois[0]
    print(f'  first: {p["name"]} ({p["lat"]:.4f},{p["lon"]:.4f})')

t = TencentMapProvider()
r = t.search_region('村', region='441426110000', page_size=20)
pois = r.data.get('pois', [])
print(f'腾讯: success={r.success}, count={len(pois)}')
if pois:
    p = pois[0]
    print(f'  first: {p["name"]} ({p["lat"]:.4f},{p["lon"]:.4f})')

# 检查 pipeline 的 cfg 是什么
print()
print('bundle.metadata.adcode_12:', bundle.metadata.adcode_12)
print('bundle.metadata.county:', bundle.metadata.county)
print('bundle.metadata.township:', bundle.metadata.township)