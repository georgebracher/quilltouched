"""Tests for the event envelope and the Sprint-0 event taxonomy."""

import dataclasses

import pytest

from everquill_engine.events import Event, EventType


def make_event(**overrides):
    base = dict(
        event_id="evt-0001",
        stream_id="character:ald",
        stream_version=1,
        world_time=86400,
        event_type=EventType.ACTION_DECLARED,
        payload_version=1,
        payload={"raw_text": "I search the archive"},
    )
    base.update(overrides)
    return Event(**base)


class TestTaxonomyStability:
    def test_exact_event_type_set(self):
        """The taxonomy, complete and exact. Additions are new
        members; existing names/values must never change or be
        repurposed (append-only applies to the vocabulary too).

        Pin updated Sprint 1 (documented reason): the A1 event store
        ADDED world_created / character_created / time_advanced
        (docs/engine/events.md "Sprint 1 additions"). No existing name
        changed — the sanctioned append-only evolution this pin exists
        to police.

        Pin updated again for the S1 review fixes (documented reason):
         ADDED content_manifest — genesis now commits the
        sha256 of the authored world YAML + loader version so an
        existing world can refuse silently-edited content. Again purely
        additive.

        Pin updated (documented reason): the claim
        lifecycle ADDED the four transition events (claim_corroborated /
        claim_contested / claim_superseded / claim_retracted — synthesis
        §2.3: transitions are events, the claim table stays a rebuildable
        projection) and narration_generated (prose canonized bound to its
        outcome event, closing the API's decision-3 TODO). Purely
        additive; claim_contradicted keeps its Sprint-0 slot unshipped."""
        assert {t.value for t in EventType} == {
            "action_declared",
            "intent_parsed",
            "outcome_resolved",
            "claim_written",
            "claim_contradicted",
            "deed_recorded",
            "timer_started",
            "timer_completed",
            "timer_aborted",
            "death_sealed",
            "heir_created",
            "title_minted",
            "entity_committed",
            # Sprint 1 additions (A1)
            "world_created",
            "character_created",
            "time_advanced",
            # Sprint 1 review fixes
            "content_manifest",
            # Claim lifecycle + narration additions
            "claim_corroborated",
            "claim_contested",
            "claim_superseded",
            "claim_retracted",
            "narration_generated",
        }

    def test_values_are_storage_names(self):
        assert EventType.DEATH_SEALED == "death_sealed"
        assert str(EventType.CLAIM_WRITTEN) == "claim_written"


class TestEnvelopeImmutability:
    def test_envelope_is_frozen(self):
        event = make_event()
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.world_time = 0
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.event_type = EventType.HEIR_CREATED

    def test_payload_is_read_only(self):
        event = make_event()
        with pytest.raises(TypeError):
            event.payload["raw_text"] = "rewritten canon"
        with pytest.raises(TypeError):
            del event.payload["raw_text"]

    def test_payload_detached_from_caller_dict(self):
        """Mutating the dict passed in must not reach into the event."""
        payload = {"raw_text": "original"}
        event = make_event(payload=payload)
        payload["raw_text"] = "tampered"
        assert event.payload["raw_text"] == "original"

    def test_payload_defaults_to_empty(self):
        event = make_event(payload={})
        assert dict(event.payload) == {}


class TestEnvelopeValidation:
    def test_stream_version_one_based(self):
        assert make_event(stream_version=1).stream_version == 1
        for bad in (0, -1):
            with pytest.raises(ValueError):
                make_event(stream_version=bad)

    def test_payload_version_one_based(self):
        assert make_event(payload_version=3).payload_version == 3
        for bad in (0, -5):
            with pytest.raises(ValueError):
                make_event(payload_version=bad)

    def test_equality_is_by_value(self):
        assert make_event() == make_event()
        assert make_event() != make_event(stream_version=2)
