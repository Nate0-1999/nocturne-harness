"""Named unbuilt acceptance rows from PLAN M3RC; a skip is not a passing proof."""

import pytest


@pytest.mark.skip(reason="r7-16: edge-on terminal stack mode is unbuilt")
def test_r7_16_deck_and_edge_on_stack_are_the_same_conversation_module() -> None:
    """SPEC D.2 154 requires one Conversation module in the edge-on and focused views."""
    pytest.fail("Replace this placeholder with edge-on Conversation acceptance proof when built")


@pytest.mark.skip(reason="r8-11: hardware tiers with different primitive budgets are unbuilt")
def test_r8_11_efficient_scene_emits_fewer_primitives_than_full_scene() -> None:
    """SPEC R10 / P2 requires the hardware tier to change actual scene cost."""
    pytest.fail("Replace this placeholder with measured primitive counts when built")


@pytest.mark.skip(reason="r9-6: per-role strongest/leaf model policies await SD-018")
def test_r9_6_compounding_workers_use_max_and_leaf_workers_use_elbow() -> None:
    """SPEC C.5 / P4.2 requires model policy to follow the error's scope."""
    pytest.fail("Replace this placeholder with role-policy acceptance proof when built")


@pytest.mark.skip(reason="r8-3: R10 superseded the Cube; flat focus camera awaits owner ruling")
def test_r8_3_focused_spatial_modules_use_the_approved_camera() -> None:
    """P2 navigation needs an owner ruling before reviving the retired Cube camera rule."""
    pytest.fail("Replace this placeholder with the owner-approved camera acceptance proof")


@pytest.mark.skip(reason="r8-7: hue-band validator is unbuilt; owner has not defined numeric bands")
def test_r8_7_palette_hues_follow_the_approved_bands() -> None:
    """SPEC B.6 leaves taste to the owner; a check must not invent color limits."""
    pytest.fail("Replace this placeholder after the owner defines the hue bands")
