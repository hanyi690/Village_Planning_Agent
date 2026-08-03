"""直接调 pipeline._from_tencent 看为什么返回空"""
import sys, os
os.environ['LOG_LEVEL'] = 'DEBUG'
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
logging.getLogger('app.modules.data').setLevel(logging.WARNING)

from app.modules.data import DataCatalog
from app.modules.data.catalog.external_anchors import ExternalAnchorPipeline

catalog = DataCatalog()
catalog.set_admin_meta('金田', province='广东省', city='梅州市',
                       county='平远县', township='泗水镇',
                       adcode_12='441426110000')
bundle = catalog.load_village_bundle('金田')
pipeline = ExternalAnchorPipeline()

# 手动调 _from_tencent 看结果
import logging
log = logging.getLogger('app.modules.data.catalog.external_anchors')
log.setLevel(logging.DEBUG)
log.handlers = []  # 移除原 handlers
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
handler.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))
log.addHandler(handler)

feats = pipeline._from_tencent('441426110000', [])
print(f'feats: {len(feats)}')
if feats:
    print(f'first: {feats[0]}')