"""Play the first-scene loop in a real browser and check each step.

  python client/scripts/first_scene.py --base http://localhost:5173 --code <invite> [--shots DIR]

Invite gate, guided creation (place six values, name, arrive), the play screen,
six tapped suggestions (one rolled, two looks and an ask), leaving the tavern for Market Row, a
workings panel, the full Chronicle with every mark open, the Character and
Codex tabs, then a reload with the local Chronicle cache cleared, so the turns
must come back from the server. Every page is scanned for the true names of
people the player has not met. Needs the API (with EVERQUILL_NARRATOR=plain, so
turns are narrated and recorded without a model) and the vite client running
against a throwaway database (README, "Running it locally"), and Playwright with
a Chromium. Prints one PASS or FAIL line per check and exits non-zero on any FAIL.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# Two looks and an ask draw several rumour seeds, so authored text gets scanned too.
TURNS = ("Look around", "about the quarry", "Size up", "Stomp the ditch slime",
         "Ask around for local news", "Look around")
MOVE = "Go to Market Row"
# Harrowdown's people, first names and surnames. "Ferrier" is left out: it is
# on a shop sign ("Ferrier's Chandlery"), which the world shows to anyone.
UNMET = re.compile(r"\b(Maren|Ostler|Jorun|Pike|Rold|Tanner|Odile|Toller|Whin|Elam|Fenn|Bracey)\b")
ACTIONS = "article.turn:not(.turn--fault):not(.turn--note)"
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f': {detail}' if detail else ''}", flush=True)
    failures += 0 if ok else 1


def tap(page: Page, label: str) -> None:
    chip = page.locator(".suggestion-chip", has_text=label).first
    if not chip.is_visible():
        page.get_by_role("button", name="More suggestions").click()
    chip.click()
    proceed = page.get_by_role("button", name="Proceed")
    try:
        proceed.wait_for(timeout=1500)
        proceed.click()
    except Exception:
        pass  # no beat for this action
    page.wait_for_timeout(1200)


RAW_ID = re.compile(r"\bnpc_[a-z0-9_]+")


def no_unmet_names(page: Page, tag: str, where: str) -> None:
    text = page.locator("body").inner_text()
    found = sorted(set(UNMET.findall(text)) | set(RAW_ID.findall(text)))
    check(f"[{tag}] no unmet person named on {where}", not found, ", ".join(found))


def full_chronicle_actions(page: Page) -> tuple[int, int]:
    """Open the full Chronicle (every mark expanded); count action blocks and
    the narrations among them."""
    opener = page.locator(".chronicle-open")
    if opener.count() == 0:
        return page.locator(ACTIONS).count(), page.locator(".turn-narration").count()
    opener.click()
    page.locator(".chronicle-scroll").wait_for(timeout=5000)
    scroll = page.locator(".chronicle-scroll")
    return scroll.locator(ACTIONS).count(), scroll.locator(".turn-narration").count()


def run(base: str, code: str, shots: Path | None, viewport: tuple[int, int]) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        ).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        tag = f"{viewport[0]}"

        def shot(name: str) -> None:
            if shots is not None:
                page.screenshot(path=str(shots / f"{tag}-{name}.png"))

        page.goto(base)
        page.get_by_label("Invite code").wait_for(timeout=15000)
        check(f"[{tag}] invite gate renders", True)
        shot("1-invite")
        page.get_by_label("Invite code").fill(code)
        page.get_by_role("button", name="Claim your volume").click()
        page.locator(".creation-chip").first.wait_for(timeout=15000)
        check(f"[{tag}] claim opens creation", True)
        shot("2-creation")
        for slot in page.locator(".creation-slot").all():
            page.locator(".creation-chip:not([disabled])").first.click()
            slot.click()
        continue_button = page.get_by_role("button", name="Continue")
        check(f"[{tag}] all six aptitudes placed", continue_button.is_enabled())
        continue_button.click()
        page.locator(".creation-name-input").fill("Wren")
        page.get_by_role("button", name="Step into Harrowdown").click()
        page.locator(".scene-canvas").wait_for(timeout=15000)
        page.wait_for_timeout(800)

        # From here on nothing should fail: watch the console and the network.
        bad: list[str] = []

        def on_console(msg) -> None:
            if msg.type == "error":
                bad.append(f"console: {msg.text}")

        def on_response(resp) -> None:
            if resp.status >= 400:
                bad.append(f"{resp.status} {resp.url}")

        page.on("console", on_console)
        page.on("response", on_response)

        check(f"[{tag}] play screen renders the scene", page.locator(".scene-stage").count() == 1)
        figures = page.locator(".sprite, .entity-label").count()
        check(f"[{tag}] the room has people and things in it", figures >= 2, f"{figures}")
        chips = page.locator(".suggestion-chip").count()
        check(f"[{tag}] suggestions are offered", chips >= 4, f"{chips}")
        no_unmet_names(page, tag, "the play screen")
        shot("3-play")

        for label in TURNS:
            tap(page, label)
        faults = page.locator("article.turn--fault").count()
        check(f"[{tag}] {len(TURNS)} tapped turns, no fault blocks", faults == 0,
              f"{faults} faults")
        page.locator(".workings-toggle").first.click()  # newest first: the latest turn
        check(f"[{tag}] a workings panel opens", page.locator(".workings").count() >= 1)
        no_unmet_names(page, tag, "the workings panel")
        shot("4-turns")

        actions, narrated = full_chronicle_actions(page)
        check(f"[{tag}] the full Chronicle holds every turn", actions >= len(TURNS), f"{actions}")
        check(f"[{tag}] every turn is narrated", narrated == actions, f"{narrated} of {actions}")
        no_unmet_names(page, tag, "the full Chronicle, marks open")
        shot("5-chronicle")
        if page.locator(".chronicle-close").count():
            page.locator(".chronicle-close").click()

        tap(page, MOVE)
        moved = "Market Row" in page.locator(".scene-canvas, header").first.inner_text()
        check(f"[{tag}] the player leaves for Market Row", moved)
        newest = page.locator("main.transcript .turn-declared").first.inner_text()
        check(f"[{tag}] the newest turn is at the top", MOVE in newest, newest)
        no_unmet_names(page, tag, "Market Row")
        shot("6-market-row")

        page.get_by_role("button", name="Character", exact=True).first.click()
        loaded = page.locator(".self-screen:not(.self-screen--boot) .self-name")
        loaded.wait_for(timeout=10000)
        check(f"[{tag}] Character shows the named character", "Wren" in loaded.inner_text())
        no_unmet_names(page, tag, "the Character tab")
        shot("7-character")
        page.get_by_role("button", name="Codex", exact=True).first.click()
        page.locator(".codex-screen:not(.codex-screen--boot)").wait_for(timeout=10000)
        cards = page.locator(".codex-card").count()
        check(f"[{tag}] Codex holds what the turns learned", cards >= 1, f"{cards}")
        no_unmet_names(page, tag, "the Codex")
        shot("8-codex")

        # Reload with the local Chronicle cache gone: canon must rebuild it.
        page.get_by_role("button", name="Play", exact=True).first.click()
        page.evaluate(
            "Object.keys(localStorage).filter(k => k.startsWith('eq_chronicle:'))"
            ".forEach(k => localStorage.removeItem(k))"
        )
        page.reload()
        page.locator(".scene-canvas").wait_for(timeout=15000)
        page.wait_for_timeout(1500)
        recovered, _ = full_chronicle_actions(page)
        check(f"[{tag}] a reload without the cache rebuilds the Chronicle from the server",
              recovered >= len(TURNS) + 1, f"{recovered}")
        shot("9-reload")
        check(f"[{tag}] no page errors", not errors, "; ".join(errors[:3]))
        check(f"[{tag}] no console errors or failed requests", not bad, "; ".join(bad[:3]))
        browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--code", action="append", required=True,
                    help="an unused invite code; give two to run phone and desktop")
    ap.add_argument("--shots", type=Path)
    a = ap.parse_args()
    if a.shots:
        a.shots.mkdir(parents=True, exist_ok=True)
    sizes = [(1280, 800), (390, 844)]
    for code, size in zip(a.code, sizes, strict=False):
        run(a.base, code, a.shots, size)
    print("FIRST SCENE PASSED" if failures == 0 else f"FIRST SCENE FAILED ({failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
