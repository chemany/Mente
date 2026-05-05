import hashlib

from mente.memory.fact_normalization import build_fact_identity


def test_build_fact_identity_normalizes_fullwidth_colons_and_space_variants():
    identity = build_fact_identity("  加入记忆：我喜欢中文回答  ")

    assert identity.normalized_fact == "我喜欢中文回答"
    assert identity.fact_key == hashlib.sha256("我喜欢中文回答".encode("utf-8")).hexdigest()


def test_build_fact_identity_classifies_supported_preference_slot():
    identity = build_fact_identity("我更喜欢中文回答")

    assert identity.normalized_fact == "我更喜欢中文回答"
    assert identity.slot_key == "preference:response_language"


def test_build_fact_identity_classifies_supported_identity_slot():
    identity = build_fact_identity("My name is Jason")

    assert identity.normalized_fact == "My name is Jason"
    assert identity.slot_key == "identity:name"
