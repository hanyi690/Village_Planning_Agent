"""Check annotation source data and layer configuration."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.modules.data import DataCatalog
import yaml

# 1. Check sources.yaml for annotation layer config
sources_path = os.path.join(os.path.dirname(__file__), "..", "app", "modules", "data", "catalog", "sources.yaml")
with open(sources_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

print("=== sources.yaml annotation-related entries ===")
for name, src in config.get("sources", {}).items():
    lt = src.get("layer_type", "")
    if "annotation" in lt or "facility" in lt or "note" in lt or "ann" in name.lower():
        print(f"  {name}: layer_type={lt} path={src.get('path','')}")

# 2. Load bundle and inspect annotations
b = DataCatalog().load_village_bundle("金田村委会")
anns = b.points.annotations_current

print(f"\n=== All annotations ({len(anns)}) ===")
for a in anns:
    print(f"  text={a.text!r} category={a.category!r} bsm={getattr(a,'bsm','')!r} ysdm={getattr(a,'ysdm','')!r} layer_type={getattr(a,'layer_type','')!r}")

# 3. Check raw GeoJSON source files
print(f"\n=== Raw source files ===")
data_dir = "F:/project/Village_Planning_Agent/data/gis/jintian"
for root, dirs, files in os.walk(data_dir):
    for fname in files:
        if fname.endswith(".geojson") or fname.endswith(".json"):
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, data_dir)
            import json
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                feats = data.get("features", [])
                if feats:
                    props = feats[0].get("properties", {})
                    print(f"  {rel}: {len(feats)} features, sample props keys: {list(props.keys())[:8]}")
            except:
                print(f"  {rel}: (parse error)")
