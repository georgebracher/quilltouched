"""Accounts v1 (interface decision 1): claim, auth, per-account worlds."""

from __future__ import annotations


class TestClaim:
    def test_claim_returns_a_device_token_and_world(self, app_client, invite_code):
        client, _ = app_client
        r = client.post("/api/claim", json={"invite_code": invite_code})
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["device_token"]) == 64  # 256-bit hex
        assert len(body["account_id"]) == 32
        assert body["world_id"] == f"harrowdown--{body['account_id'][:8]}"

    def test_unknown_invite_code_is_403(self, app_client, invite_code):
        client, _ = app_client
        r = client.post("/api/claim", json={"invite_code": "not-a-real-code"})
        assert r.status_code == 403

    def test_invite_code_is_single_use_and_indistinguishable_from_unknown(
        self, app_client, invite_code
    ):
        """A used code answers EXACTLY like an unknown one (status
        AND body) — no validity-state oracle for guessing attacks."""
        client, _ = app_client
        first = client.post("/api/claim", json={"invite_code": invite_code})
        assert first.status_code == 200
        used = client.post("/api/claim", json={"invite_code": invite_code})
        unknown = client.post("/api/claim", json={"invite_code": "not-a-real-code"})
        assert used.status_code == 403
        assert unknown.status_code == 403
        assert used.json() == unknown.json()

    def test_claim_body_is_validated(self, app_client, invite_code):
        client, _ = app_client
        assert client.post("/api/claim", json={}).status_code == 422
        assert client.post("/api/claim", json={"invite_code": ""}).status_code == 422
        assert (
            client.post(
                "/api/claim", json={"invite_code": invite_code, "extra": 1}
            ).status_code
            == 422
        )


class TestAuth:
    def test_open_endpoints_stay_open(self, app_client, invite_code):
        client, _ = app_client
        assert client.get("/healthz").text == "ok"
        assert client.get("/api/hello").json()["status"] == "alive"

    def test_unauthed_action_is_410_shared_world_sealed(self, app_client, invite_code):
        client, _ = app_client
        r = client.post("/api/action", json={"command_id": "t1", "intent": {}})
        assert r.status_code == 410
        assert "sealed" in r.json()["detail"].lower()

    def test_unknown_token_is_401(self, app_client, invite_code):
        client, _ = app_client
        r = client.post(
            "/api/action",
            json={"command_id": "t1", "intent": {}},
            headers={"authorization": "Bearer " + "0" * 64},
        )
        assert r.status_code == 401
        r = client.get("/api/scene", headers={"authorization": "Bearer nope"})
        assert r.status_code == 401


class TestPerAccountWorlds:
    def test_authed_scene_bootstraps_the_accounts_own_world(self, app_client, invite_code):
        client, _ = app_client
        claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
        headers = {"authorization": f"Bearer {claimed['device_token']}"}

        r = client.get("/api/scene", headers=headers)
        assert r.status_code == 200, r.text
        scene = r.json()
        assert scene["world"] == claimed["world_id"]
        assert scene["location"]["type"] == "tavern"  # dev PC starts in the tavern
        entity_ids = {e["id"] for e in scene["entities"]}
        assert "npc_harrowdown_maren_ostler" in entity_ids
        # KnownState surface only: no sheet-shaped fields anywhere.
        assert "aptitudes" not in r.text and "hp" not in r.text

    def test_world_id_mismatch_is_404(self, app_client, invite_code):
        client, _ = app_client
        claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
        headers = {"authorization": f"Bearer {claimed['device_token']}"}
        r = client.get("/api/scene?world=harrowdown--ffffffff", headers=headers)
        assert r.status_code == 404

    def test_legacy_shared_world_stays_readable_unauthed(
        self, clean_legacy_world, app_client, invite_code
    ):
        client, _ = app_client
        r = client.get("/api/scene?world=harrowdown")
        assert r.status_code == 200
        assert r.json()["world"] == "harrowdown"
