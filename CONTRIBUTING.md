# Contributing

## Branches

```
master   ──●───────────────●──────────   releases / tagged, always green
            \             /
develop  ────●───●───●───●───●───●────   integration branch, always green
              \     /     \     /
feature/x  ────●──●        ●──●          one branch per change, merged by PR
```

| Branch | Purpose | Who pushes |
|---|---|---|
| `master` | What is released. Only ever updated by a PR from `develop` (or a `hotfix/*` branch). Tag releases here (`v0.1.0`). | nobody directly |
| `develop` | Integration branch. Everything lands here first by PR. | nobody directly |
| `feature/<topic>`, `fix/<topic>`, `docs/<topic>` | One change each, branched from `develop`. | the author |
| `hotfix/<topic>` | Branched from `master` for an urgent fix; PR to `master`, then merge `master` back into `develop`. | the author |

Both `master` and `develop` are protected: no direct pushes, PRs only, the `ci` status must be
green and the branch must be up to date with its base.

## A change, start to finish

```sh
git switch develop && git pull
git switch -c feature/qt-quick-seam
# … work, commit in small steps …
python3 -m unittest discover -s tests          # driver + scenario tests, no Qt needed
tests/smoke.sh                                 # builds the sample app, plays the scenario
git push -u origin feature/qt-quick-seam
gh pr create --base develop --fill             # or the GitHub UI
```

Squash-merge or rebase-merge into `develop`; keep the history linear. When `develop` is in a
state worth releasing, open a PR `develop → master`, merge it (merge commit, so `master`
keeps the real history), and tag.

## What CI runs on a PR

`.github/workflows/ci.yml`:

1. **python tests** — `tests/test_perfdrive.py` drives `tools/perfdrive.py` against
   `tests/fake_app.py` (speaks the perfdriver protocol, no Qt); `tests/test_scenarios.py`
   checks that every `scenarios/*.json` is playable. Plus `pyflakes`.
2. **smoke / linux / Qt 5 and Qt 6** — builds `sample-app/` with the seam and plays
   `scenarios/sample_app.json` in the headless lane (`tests/smoke.sh`).
3. **smoke / windows / Qt 6** — the same on a Windows runner.

These prove the tooling works; they do not measure performance. GitHub runners are shared
machines and the numbers in the uploaded `results/*.json` artifacts are only good for
spotting that something broke by an order of magnitude. Real measurements belong on the
dedicated Jenkins agents described in `docs/agents.md`.

## Decisions

Why the framework is shaped the way it is: [`docs/adrs/`](docs/adrs/README.md). Add a record
when a choice is hard to reverse, would surprise a reader of the code, and had real alternatives.

## Conventions

- Python: standard library only in `tools/` (it runs on bare Jenkins agents). 3.8+.
- C++: C++17, Qt 5.15 and Qt 6 both supported, no extra Qt modules in the seam.
- Changes the sample app needs for testability go into `sample-app/testing-changes.diff`
  as well, so the diff stays a complete recipe for instrumenting a real app.
- Commit messages: imperative subject line, a body explaining *why* when it is not obvious.
