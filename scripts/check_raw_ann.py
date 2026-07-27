"""Check raw annotation GeoJSON properties."""
import json

with open("data/gis/jintian/current/annotation.geojson", encoding="utf-8") as f:
    data = json.load(f)

for i, feat in enumerate(data["features"][:10]):
    props = feat["properties"]
    text_val = props.get("注记", "")
    cat_val = props.get("分类", "")
    coords = feat["geometry"]["coordinates"]
    print(f"[{i}] 注记={text_val!r} 分类={cat_val!r} coords={coords}")

# Check encoding issue: maybe text is in a different field
print("\n=== All property keys ===")
keys = set()
for f in data["features"]:
    keys.update(f["properties"].keys())
print(keys)

# Check if 注记 field has content
non_empty = sum(1 for f in data["features"] if f["properties"].get("注记", "").strip())
print(f"\nFeatures with non-empty 注记: {non_empty}/{len(data['features'])}")
