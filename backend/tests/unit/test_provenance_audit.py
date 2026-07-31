from app.modules.schema.provenance.audit import ProvenanceAudit, ProvenanceSource


def test_audit_records_and_reports():
    audit = ProvenanceAudit()
    audit.record("primary_zone", ProvenanceSource.MISSING_UPPER_PLAN, parcel_count=660)
    entries = audit.report()
    assert len(entries) == 1
    assert entries[0].layer == "primary_zone"
    assert entries[0].source == "missing:upper_plan_transmission"
    assert entries[0].parcel_count == 660


def test_audit_missing_layers_filters():
    audit = ProvenanceAudit()
    audit.record("planning_zone", ProvenanceSource.DERIVED_UPPER_PLAN_OVERLAY, parcel_count=10)
    audit.record("three_line.urban_dev_boundary", ProvenanceSource.MISSING_URBAN_DEV_BOUNDARY, parcel_count=0)
    missing = audit.missing_layers()
    assert len(missing) == 1
    assert missing[0].layer == "three_line.urban_dev_boundary"


def test_audit_record_supports_optional_note():
    audit = ProvenanceAudit()
    audit.record("x", ProvenanceSource.CUSTOM_VOCABULARY, parcel_count=3, note="blocked by redline")
    assert audit.report()[0].note == "blocked by redline"