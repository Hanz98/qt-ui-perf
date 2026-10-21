---
status: accepted
date: 2026-10-19
---
# GitHub Actions proves the tooling works; it never produces performance numbers

The public repository runs `.github/workflows/ci.yml` on every pull request: driver tests
against a fake application, and a build-and-play of the sample apps on Linux (Qt 5 and 6)
and Windows (Qt 6). Those runs upload their results JSON, but nothing compares or gates on
them: GitHub runners are shared, variably loaded machines (0003 again). Real measurements
happen on the dedicated agents in `ci/Jenkinsfile`. The branch model is `master` for
releases, `develop` for integration, feature branches merged by pull request with the `ci`
status required; the two protected branches exist so that a tagged release is always a
state that passed the tooling checks on all three platforms.
