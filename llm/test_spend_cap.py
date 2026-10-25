"""spend_cap prices each response and refuses a call that could pass the cap.
Offline: the SDK method underneath is a fake that returns fixed usage."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from anthropic.resources.messages import Messages

from llm import spend_cap

# A request about 8,000 tokens long (24,000 characters at three a token), with
# room for 200 output tokens: its worst case is about $0.011 on haiku.
SCRIPT = """
import anthropic
client = anthropic.Anthropic(api_key="test-key")
for _ in range({calls}):
    client.messages.create(
        model="claude-haiku-4-5", max_tokens=200,
        messages=[{{"role": "user", "content": "x" * 23960}}],
    )
"""


def _run(monkeypatch, tmp_path, *, calls, cap, create=None):
    def fake_create(self, **kwargs):
        # 8,000 input + 200 output tokens on haiku: $0.008 + $0.001 = $0.009
        return SimpleNamespace(usage=SimpleNamespace(
            input_tokens=8000, output_tokens=200,
            cache_read_input_tokens=0, cache_creation_input_tokens=0))

    monkeypatch.setattr(Messages, "create", create or fake_create)
    script = tmp_path / "job.py"
    script.write_text(SCRIPT.format(calls=calls))
    monkeypatch.setattr(sys, "argv", ["spend_cap", "--max-usd", str(cap), str(script)])
    reports = []
    monkeypatch.setattr(spend_cap.atexit, "register", reports.append)
    try:
        spend_cap.main()
        error = None
    except spend_cap.SpendCapReached as exc:
        error = exc
    return reports, error


def test_measures_the_spend(monkeypatch, tmp_path, capsys):
    reports, error = _run(monkeypatch, tmp_path, calls=3, cap=1.0)
    assert error is None
    reports[0]()
    assert "SPEND: $0.0270 over 3 calls" in capsys.readouterr().out


def test_refuses_the_call_that_could_pass_the_cap(monkeypatch, tmp_path, capsys):
    reports, error = _run(monkeypatch, tmp_path, calls=10, cap=0.03)
    assert isinstance(error, spend_cap.SpendCapReached)
    reports[0]()
    assert "over 3 calls" in capsys.readouterr().out  # 0.027 spent + a 0.011 worst case


def test_a_zero_cap_refuses_the_first_call(monkeypatch, tmp_path, capsys):
    """The old cap reserved nothing until a call had been priced, so the first
    call (and a first wave of parallel calls) went out at any cap (codex-004)."""
    reports, error = _run(monkeypatch, tmp_path, calls=1, cap=0.0)
    assert isinstance(error, spend_cap.SpendCapReached)
    reports[0]()
    assert "over 0 calls" in capsys.readouterr().out


def test_a_failed_call_releases_its_reservation(monkeypatch, tmp_path, capsys):
    calls = {"n": 0}

    def flaky(self, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise ConnectionError("dropped")
        return SimpleNamespace(usage=SimpleNamespace(
            input_tokens=8000, output_tokens=200,
            cache_read_input_tokens=0, cache_creation_input_tokens=0))

    script_calls = 4
    monkeypatch.setattr(Messages, "create", flaky)
    script = tmp_path / "job.py"
    script.write_text(
        "import anthropic\nclient = anthropic.Anthropic(api_key='k')\n"
        f"for _ in range({script_calls}):\n"
        "    try:\n"
        "        client.messages.create(model='claude-haiku-4-5', max_tokens=200,\n"
        "            messages=[{'role': 'user', 'content': 'x' * 23960}])\n"
        "    except ConnectionError:\n"
        "        pass\n"
    )
    monkeypatch.setattr(sys, "argv", ["spend_cap", "--max-usd", "0.015", str(script)])
    reports = []
    monkeypatch.setattr(spend_cap.atexit, "register", reports.append)
    spend_cap.main()  # three dropped calls leave nothing reserved; the fourth fits
    reports[0]()
    assert "over 1 calls" in capsys.readouterr().out
