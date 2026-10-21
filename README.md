# CLSEN Data Web — public CI snapshot

This repository is a one-way, history-free source snapshot of the private
development repository. `public-ci-source.json` records the exact original
commit, tree, canonical Git blob and export SHA-256 of each file. The public Git commit is a
different identity and its CI must not be reported as a private PR check.

The only executable workflow is `public-ci.yml`. It uses standard ephemeral
GitHub-hosted Ubuntu/Windows runners, complete canonical backend/frontend
profiles and **MySQL 8.4 only**, with the original 110-minute test and
120-minute job budgets and independent always-run container cleanup.

Private runner/release workflow definitions are archived under
`.github/private-workflow-reference/`. Preparation verifies the source hashes
using canonical Git blobs (including normalized Windows line endings) and
restores them inside each ephemeral checkout solely so unchanged source
contract tests can read them. They are not dispatched, and their self-hosted
policy is not the public workflow's policy. Public-runner policy is checked
separately by `test_public_ci_workflow.py`.

No source `data/`, local `.env`, private fixture, deployment secret, private
Git history or uncommitted working-tree change is included. The encrypted
backup fixtures and test key are explicitly synthetic public test material,
as documented in their fixture README. CI has no production credentials or
network connection to the private runners. No release/deployment workflow
is enabled here. Passing public CI is not production acceptance or release.
