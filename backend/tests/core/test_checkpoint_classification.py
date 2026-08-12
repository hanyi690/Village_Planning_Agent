from app.infrastructure.checkpoint.checkpoint_policy import classify_checkpoint


def test_layer_checkpoint_does_not_require_legacy_is_interrupted_flag():
    stable, kind = classify_checkpoint({
        "previous_layer": 2,
        "layer_just_completed": 2,
        "phase": "layer2",
    })

    assert stable is True
    assert kind == "layer"


def test_pending_interrupt_is_classified_as_human_checkpoint():
    stable, kind = classify_checkpoint(
        {"phase": "layer3"},
        pending_interrupt=True,
    )

    assert stable is True
    assert kind == "human"
