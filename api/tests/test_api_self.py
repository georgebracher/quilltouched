"""GET /api/self (the Self view surface).

Pins the shape the client's Self screen wires against, on a freshly-claimed
world (own build known; standing empty until the PC acts), plus auth. The
disposition/standing content path is exercised by the engine's social tests and
the live-verify; here we pin the contract shape and the own-build exposure.
"""

from __future__ import annotations


def _claim(client, invite_code) -> dict[str, str]:
    claimed = client.post("/api/claim", json={"invite_code": invite_code}).json()
    return {"authorization": f"Bearer {claimed['device_token']}"}


class TestSelf:
    def test_self_requires_auth(self, app_client, invite_code):
        client, _ = app_client
        assert client.get("/api/self").status_code == 401

    def test_self_shape_on_fresh_world(self, app_client, invite_code):
        client, _ = app_client
        headers = _claim(client, invite_code)
        r = client.get("/api/self", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {
            "world", "character_id", "name", "origin", "aptitudes",
            "hp", "hp_max", "wounds", "coin", "named_abilities",
            "marks", "dispositions", "standings", "renown", "renown_descriptor",
        }
        # The player KNOWS their own build (unlike an NPC's hidden true sheet).
        assert set(body["aptitudes"]) == {
            "might", "finesse", "wits", "will", "presence", "lore"
        }
        assert isinstance(body["wounds"], str)  # a word, never a raw hp number
        assert body["marks"] == []
        # Earned standing is empty until the PC acts.
        assert body["dispositions"] == [] and body["standings"] == []
        assert body["renown"] == 0 and isinstance(body["renown_descriptor"], str)
