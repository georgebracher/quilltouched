"""The client's per-sprite art metrics (client/src/scene-art.ts SPRITE_ART) must
cover exactly the committed sprites, or a new sprite falls back to a name label
without anyone noticing (audit 2026-10-24, k3 F14). Skipped where the art is not
present: the public copy ships no images, so there it checks nothing (a skip
would fail the release gate, which treats any skip as broken)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "assets" / "sprites" / "manifest.json"
SCENE_ART = ROOT / "client" / "src" / "scene-art.ts"
PUBLIC_SPRITES = ROOT / "client" / "public" / "sprites"


def test_every_committed_sprite_has_art_metrics_and_a_served_png():
    if not MANIFEST.exists():
        return  # no art in this copy (the public export)
    manifest_ids = {row["entity_id"] for row in json.loads(MANIFEST.read_text())}
    block = SCENE_ART.read_text().split("const SPRITE_ART", 1)[1].split("\n}\n", 1)[0]
    metric_ids = set(re.findall(r"'([a-z]+\.[a-z_]+\.[a-z_]+)':", block))
    assert metric_ids == manifest_ids
    served = {p.stem for p in PUBLIC_SPRITES.glob("*.png")}
    assert manifest_ids <= served
