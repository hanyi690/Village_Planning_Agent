from app.modules.data.encoding_detector import detect_encoding
from app.modules.schema.provenance import ProvenanceSource


def test_detect_gbt21010_returns_correct_source():
    assert detect_encoding("0301") == ProvenanceSource.GBT21010
    assert detect_encoding("0702") == ProvenanceSource.GBT21010
    assert detect_encoding("1104") == ProvenanceSource.GBT21010


def test_detect_appendix5_returns_correct_source():
    assert detect_encoding("1340") == ProvenanceSource.PRACTICAL_APPENDIX5
    assert detect_encoding("2121") == ProvenanceSource.PRACTICAL_APPENDIX5


def test_detect_unknown_returns_none():
    assert detect_encoding("9999") is None
    assert detect_encoding("") is None
    assert detect_encoding("not-a-code") is None


def test_detect_tugui_returns_tugui():
    assert detect_encoding("0110") == ProvenanceSource.TUGUI
    assert detect_encoding("2030") == ProvenanceSource.TUGUI


def test_detect_vne_returns_vne():
    assert detect_encoding("V11") == ProvenanceSource.VNE
    assert detect_encoding("E1") == ProvenanceSource.VNE


def test_jintian_routes_1340_to_appendix5():
    assert detect_encoding("1340") == ProvenanceSource.PRACTICAL_APPENDIX5