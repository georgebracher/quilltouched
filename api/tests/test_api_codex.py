"""The Codex surface + status-strip facts.

Contract-shape coverage for GET /api/codex, POST /api/hypothesis, and the
`facts` block on GET /api/scene. The actual research -> fact-card path is
content-driven (a source + scope in the world YAML) and is exercised in the
live-verify against production; here we pin the shapes the client (the client's
client/src/api.ts CodexResponse / CodexClaim / StatusFacts) wires against, plus
auth + validation, on a freshly-bootstrapped world (no Inquiry claims yet).
"""

from __future__ import annotations


def _claim(client, invite_code) -> dict[str, str]:
    claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
    return {"authorization": f"Bearer {claimed['device_token']}"}


class TestStatusFacts:
    def test_scene_carries_status_facts(self, app_client, invite_code):
        client, _ = app_client
        headers = _claim(client, invite_code)
        r = client.get("/api/scene", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exits"] == [
            {"id": "loc_harrowdown_market_row", "name": "Market Row", "carriage_days": 0}
        ]
        facts = body["facts"]
        assert facts is not None
        assert isinstance(facts["coin"], int)  # Chronicle-exact numerals
        assert isinstance(facts["active_timers"], list)
        for timer in facts["active_timers"]:
            assert set(timer) == {"timer_id", "kind", "label", "due_world_date"}
            # never a raw minute: the Chronicle rendering "Day N, HH:MM"
            assert timer["due_world_date"].startswith("Day ")
        # still leak-safe: no true-sheet numbers leaked by the facts block
        assert "aptitudes" not in r.text and "hp_max" not in r.text


class TestCodex:
    def test_codex_requires_auth(self, app_client, invite_code):
        client, _ = app_client
        assert client.get("/api/codex").status_code == 401

    def test_codex_shape_on_fresh_world(self, app_client, invite_code):
        client, _ = app_client
        headers = _claim(client, invite_code)
        r = client.get("/api/codex", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"world_id", "world_date", "claims", "known_locations"}
        assert isinstance(body["claims"], list)  # empty until the PC researches
        # map-in-Codex v0: the starting location is a SEEN place
        locs = body["known_locations"]
        assert isinstance(locs, list) and len(locs) >= 1
        for loc in locs:
            assert set(loc) == {"location_id", "name", "region"}
        # a fact card, when present, never carries a raw sheet number
        for card in body["claims"]:
            assert set(card) == {
                "claim_id", "subject_entity_id", "subject_label", "claim_text",
                "value_or_range", "source", "observer", "method", "world_date",
                "scope", "confidence", "status", "journal_flag", "predicate",
                "hop_count", "contested_by_claim_id",
            }

    def test_codex_source_filter_is_harmless(self, app_client, invite_code):
        client, _ = app_client
        headers = _claim(client, invite_code)
        r = client.get("/api/codex?source=nothing-matches", headers=headers)
        assert r.status_code == 200
        assert r.json()["claims"] == []


class TestHypothesis:
    def test_hypothesis_requires_auth(self, app_client, invite_code):
        client, _ = app_client
        r = client.post("/api/hypothesis", json={"claim_ids": ["x"]})
        assert r.status_code == 401

    def test_hypothesis_validates_body(self, app_client, invite_code):
        client, _ = app_client
        headers = _claim(client, invite_code)
        assert client.post("/api/hypothesis", json={}, headers=headers).status_code == 422
        assert (
            client.post(
                "/api/hypothesis", json={"claim_ids": []}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/hypothesis", json={"claim_ids": ["x"], "bad": 1}, headers=headers
            ).status_code
            == 422
        )

    def test_hypothesis_ignores_unheld_claims(self, app_client, invite_code):
        client, _ = app_client
        headers = _claim(client, invite_code)
        r = client.post(
            "/api/hypothesis",
            json={"claim_ids": ["not-a-real-claim"], "note": "a hunch"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        # no held claims match -> no target, never an existence oracle
        assert r.json() == {"research_targets": []}
