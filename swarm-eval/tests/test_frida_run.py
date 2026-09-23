"""frida-run resident mode + auto-foreground (env-hardening ticket 01).

Device-free proof of the runner's lifecycle contract. `sandbox/frida-run` is a shebang script,
not an importable module, and it `import frida` at top level — which the sandbox has but a host
test env may not. So we load its source with a stub `frida` injected: the tests exercise the pure
lifecycle/parse/foreground logic without a device or the real frida client.

Covers:
- `_done_outcome`: the resident-vs-non-resident `done` semantics (criteria 1 & 2).
- `_build_parser`: the new flags parse, the DEFAULT path is the old non-resident behaviour, and
  the existing required-target + mutual-exclusion guards still hold (criterion 2).
- `_foreground`: a spawn is brought forward via activity-manager `am start` (preferred), with a
  `monkey` fallback only when no component resolves / `am start` errors (criterion 3).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_RUNNER = Path(__file__).resolve().parent.parent / "sandbox" / "frida-run"


def _load_runner():
    """Load `sandbox/frida-run` as a module object with a stub `frida` (no device needed)."""
    stub = types.ModuleType("frida")
    stub.get_usb_device = lambda *a, **k: None  # never called by these tests
    sys.modules.setdefault("frida", stub)
    mod = types.ModuleType("frida_run_under_test")
    exec(compile(_RUNNER.read_text(), str(_RUNNER), "exec"), mod.__dict__)
    return mod


fr = _load_runner()


# --- lifecycle contract: `done` semantics (criteria 1 & 2) ---------------------------------

def test_done_outcome_non_resident_unchanged():
    # DEFAULT (non-resident): a `done` ends the run — ok -> 0, not-ok -> 2 (the shipped behaviour).
    assert fr._done_outcome(True, keep_alive=False) == 0
    assert fr._done_outcome(False, keep_alive=False) == 2


def test_done_outcome_resident_ignores_done():
    # RESIDENT: a `done` is informational and must NOT tear the session down (returns None).
    assert fr._done_outcome(True, keep_alive=True) is None
    assert fr._done_outcome(False, keep_alive=True) is None


# --- parser: new flags + unchanged defaults/guards (criterion 2) ----------------------------

def test_parser_defaults_are_non_resident():
    a = fr._build_parser().parse_args(["-a", "com.x", "-l", "a.js"])
    assert a.keep_alive is False        # resident mode is opt-in
    assert a.no_foreground is False     # foreground-after-spawn is the default
    assert a.activity is None
    assert a.timeout == 60.0            # unchanged default window


def test_parser_resident_and_foreground_flags():
    a = fr._build_parser().parse_args(
        ["-f", "com.x", "-l", "a.js", "-k", "-t", "0", "--no-foreground", "--activity", "com.x/.M"]
    )
    assert a.keep_alive is True
    assert a.no_foreground is True
    assert a.timeout == 0.0
    assert a.activity == "com.x/.M"


@pytest.mark.parametrize("argv", [
    ["-a", "com.x"],                       # missing required -l
    ["-l", "a.js"],                        # no target (-a/-f)
    ["-l", "a.js", "-a", "x", "-f", "y"],  # -a and -f are mutually exclusive
])
def test_parser_still_rejects_bad_invocations(argv):
    with pytest.raises(SystemExit):
        fr._build_parser().parse_args(argv)


# --- auto-foreground: prefer `am start`, fall back to monkey (criterion 3) -------------------

class _Rec:
    """Records subprocess.run argv and replays scripted results (returncode/stdout/stderr)."""

    def __init__(self, results):
        self.calls: list[list[str]] = []
        self._results = list(results)

    def __call__(self, argv, *a, **k):
        self.calls.append(argv)
        rc, out, err = self._results.pop(0)
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _amcmd(calls):
    return next((c for c in calls if "am" in c and "start" in c), None)


def _monkeycmd(calls):
    return next((c for c in calls if "monkey" in c), None)


def test_foreground_prefers_am_start_with_explicit_activity(monkeypatch):
    rec = _Rec([(0, "Starting: Intent ...", "")])  # am start succeeds
    monkeypatch.setattr(fr.subprocess, "run", rec)
    fr._foreground("com.example.app", "com.example.app/.MainActivity")
    am = _amcmd(rec.calls)
    assert am and am[-1] == "com.example.app/.MainActivity"   # exact component to am start -n
    assert _monkeycmd(rec.calls) is None                      # monkey NOT used when am start works


def test_foreground_resolves_activity_when_not_given(monkeypatch):
    # first call resolves the launcher component; second is the am start that consumes it
    rec = _Rec([(0, "com.example.app/.Main\n", ""), (0, "Starting: Intent ...", "")])
    monkeypatch.setattr(fr.subprocess, "run", rec)
    fr._foreground("com.example.app", None)
    assert any("resolve-activity" in c for c in rec.calls)    # it resolved, not guessed
    am = _amcmd(rec.calls)
    assert am and am[-1] == "com.example.app/.Main"
    assert _monkeycmd(rec.calls) is None


def test_foreground_falls_back_to_monkey_when_am_start_errors(monkeypatch):
    # explicit component, but am start reports an Error -> monkey fallback fires
    rec = _Rec([(0, "", "Error: Activity not started"), (0, "", "")])
    monkeypatch.setattr(fr.subprocess, "run", rec)
    fr._foreground("com.example.app", "com.example.app/.Bad")
    assert _amcmd(rec.calls) is not None                      # it tried am start first
    monkey = _monkeycmd(rec.calls)
    assert monkey and "com.example.app" in monkey and "android.intent.category.LAUNCHER" in monkey


def test_foreground_falls_back_to_monkey_when_no_component_resolves(monkeypatch):
    # no activity given and resolution yields nothing usable -> straight to monkey, no am start
    rec = _Rec([(0, "No activity found\n", ""), (0, "", "")])
    monkeypatch.setattr(fr.subprocess, "run", rec)
    fr._foreground("com.example.app", None)
    assert _amcmd(rec.calls) is None
    assert _monkeycmd(rec.calls) is not None
