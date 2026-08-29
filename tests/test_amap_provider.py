import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.data.ingestion.providers.amap.provider import AmapProvider
from app.data.ingestion.providers.amap.types import AmapResult


def test_parse_pois_preserves_optional_fields_and_coordinate_forms():
    provider = AmapProvider()
    parsed = provider._parse_pois([
        {
            "id": "p1",
            "name": "测试设施",
            "location": "116.044146,24.818629",
            "typecode": "141200",
            "children": [{"id": "child-1"}],
            "business": {"tel": "0753"},
        }
    ])[0]

    assert parsed["id"] == "p1"
    assert parsed["children"] == [{"id": "child-1"}]
    assert parsed["business"] == {"tel": "0753"}
    assert parsed["location_gcj02"] == [116.044146, 24.818629]
    assert parsed["lon"] != parsed["lon_gcj02"]
    assert parsed["coordinate_contract"].startswith("AMap response GCJ-02")


def test_reverse_geocode_requests_all_documented_collections(monkeypatch):
    provider = AmapProvider()
    captured = {}

    def fake_request(url, params):
        captured["url"] = url
        captured["params"] = dict(params)
        return AmapResult(
            success=True,
            data={
                "regeocode": {
                    "formatted_address": "广东省梅州市平远县泗水镇金田村",
                    "addressComponent": {},
                    "roads": [{"id": "r1", "name": "Y122"}],
                    "roadinters": [{"first_name": "Y122"}],
                    "pois": [{"id": "p1", "name": "村委会"}],
                    "aois": [{"name": "金田村"}],
                    "neighborhood": {"name": "金田村"},
                    "building": {"name": "村委会"},
                }
            },
        )

    monkeypatch.setattr(provider, "_request", fake_request)
    result = provider.reverse_geocode(116.04, 24.82)

    assert captured["params"]["extensions"] == "all"
    assert captured["params"]["roadlevel"] == "0"
    assert captured["params"]["radius"] == "3000"
    assert result.data["roads"][0]["name"] == "Y122"
    assert result.data["roadinters"][0]["first_name"] == "Y122"
    assert result.data["pois"][0]["id"] == "p1"
    assert result.data["aois"][0]["name"] == "金田村"
    assert result.data["raw_regeocode"]["building"]["name"] == "村委会"
