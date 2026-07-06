# tests/ — pytest + pytest-asyncio

Single flat `tests/` dir (28 files). No unit/integration/e2e split. `pytest.ini` only sets `testpaths = tests`. `conftest.py` only bootstraps `sys.path` — **no shared fixtures**.

## Test File Inventory (by domain)

**Flow / regression** (stateful, async, `temp_db`)
- `test_services_flow.py`, `test_m2_flow.py`, `test_m3_flow.py`, `test_m4_flow.py` — milestone integration flows.
- `test_auto_seclusion.py`, `test_vitals.py`, `test_settle.py`, `test_breakthrough.py` — growth/regen loops.
- `test_economy.py`, `test_sinks.py`, `test_market.py`, `test_inventory_bound.py` — economy edge cases.
- `test_dao_path.py`, `test_daohang.py`, `test_ascension.py` — late-game systems.
- `test_combat.py`, `test_buff_caps.py` — combat engine bounds.
- `test_db_isolation.py` — dual-conn WAL/concurrency invariant.
- `test_audit_fixes.py`, `test_review_followups.py`, `test_playability_issues.py`, `test_issue65_equipment.py` — issue regression guards.
- `test_menu_unification.py`, `test_spec_polish.py` — UI / spec conformance.

**Pure / sync** (no DB, no asyncio)
- `test_balance.py` — economy/config assertions.
- `test_huashen_config.py`, `test_huashen_loop.py` — 化神 realm config.
- `test_dao_path_sinks.py` — `balance_sim` model metrics.
- `test_breakthrough.py` (sync portion) — realm progression arithmetic.

## Required `temp_db` Fixture Template
Copy verbatim into every stateful test module:
```python
import pytest_asyncio
from models import db

@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "t.db"))
    yield
    await db.close_db()
```
Then: `async def test_x(temp_db): ...` with `@pytest.mark.asyncio`.

## Mocking Strategy
- **No `unittest.mock`**, no `pytest-mock`, no `responses`.
- Use `monkeypatch.setattr(module, "fn", replacement)`.
- **Deterministic RNG**: inline classes like `StableRng`/`_FakeRng` to force combat/loot branches. Seed `0..N-1` for sweep tests (see `test_balance.py`).
- **Fake bots**: when a service takes a `bot` argument, define a local class:
  ```python
  class FakeBot:
      def __init__(self): self.sent = []
      async def send_message(self, chat_id, text, **kw): self.sent.append((chat_id, text))
  class FailingBot(FakeBot):
      async def send_message(self, *a, **kw): raise RuntimeError("boom")
  ```
  See `test_market.py`, `test_playability_issues.py`, `test_spec_polish.py`.
- **Fake callbacks**: `FakeCallback` with `.from_user.id`, `.data`, `.message.chat`, `.answer()`, `.bot` for token-flow tests (see `test_spec_polish.py`).

## Conventions
- One `test_*.py` per feature/issue. Don't merge unrelated tests.
- Flow tests named `test_m<N>_flow.py` for milestone-tagged integration.
- Issue-regression tests named `test_issue<NN>_<topic>.py`.
- Test fn names: `test_<scenario>_<expected_outcome>`.
- DB state setup: call service fns (`character.register(...)`) OR raw `db.execute("INSERT ...")`. Both acceptable; pick clearer option.
- Time mocking: `monkeypatch.setattr(time, "time", lambda: <fixed>)` for regen/settle tests.
- No coverage config — don't add `.coveragerc` silently.

## Running
```bash
python -m pytest                          # all
python -m pytest tests/test_combat.py     # single file
python -m pytest -k balance               # by keyword
python -m tools.balance_sim               # balance sim (not a test, but companion)
```

## Anti-patterns
- Don't add `unittest.mock.MagicMock` — break with the project style.
- Don't share a `conftest.py` fixture for DB — each module owns its `temp_db` (isolates state per file).
- Don't write sync tests for service fns that touch DB — mark `@pytest.mark.asyncio` + `temp_db`.
- Don't drop `await db.close_db()` from fixture teardown — leaks conns across tests.
- Don't assert on Chinese text literals — brittle to copy edits; assert on `status` keys instead.
