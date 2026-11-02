# Releases

The [workflow](../.github/workflows/release.yml) checks incoming commits, builds
and tests distributions, then publishes release-causing `main` changes to GitHub
Releases and PyPI. It uses Python Semantic Release's parser and version algorithm.

## Commit rules

| Commit | Version change |
| --- | --- |
| `feat: ...` | Minor |
| `fix: ...`, `perf: ...` | Patch |
| `type!: ...` or a `BREAKING CHANGE:` footer | Minor before 1.0; major thereafter |
| Ordinary docs, maintenance, tests, refactors | No release |

CI validates every incoming non-merge commit. Prefer rebase merging to preserve
the validated messages; squash merges also need a valid final message. To check
one locally, install `requirements-release.txt` and run:

```sh
python release_plan.py lint --message-file PATH
```

The first product version is `0.1.0`; tags use `trame-vtkjs-vX.Y.Z`. The baseline
in `pyproject.toml` excludes inherited history from initial message validation
and version calculation. No generated version/changelog commit changes the
source revision after testing.

## Publisher setup

Keep Actions disabled while seeding the new repository. Its initial `main` must
already contain the exact `baseline_commit` configured in `pyproject.toml`,
including the identity rename and its shipping ancestry. Open the release/docs
PR from that baseline, and rebase only the commits after it. Rebase-merging the
entire migration from an earlier shipping commit would rewrite the required
baseline and prevent release planning. The initial seed therefore includes the
identity rename; review it before authorizing that push. Preserve the old
repository's tags/assets for existing wheel URLs. Enable Actions only when
the release-capable merge is intended to publish.

Register a PyPI [pending trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
or update an existing project's publisher with these fields:

| Field | Value |
| --- | --- |
| PyPI project | `trame-vtkjs` |
| GitHub owner / repository | `PaulHax` / `trame-vtkjs` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Create the matching GitHub environment, allow `main` releases, and configure
branch protection and merge settings. Build jobs have read-only repository
access. Only the GitHub release job has `contents: write`; only the separate
PyPI job has `id-token: write`. No PyPI token is stored in the repository.

## Artifacts and recovery

A source-bound plan selects the public version before building. CI verifies
that the wheel and sdist contain identical runtime files, installs/tests the
wheel, and transfers those artifacts to publication jobs. Those jobs do not
rebuild source. Evidence records source/tree, upstream pins, and artifact hashes.

Existing GitHub assets and PyPI digests must match the tested bytes. Exact-byte
reruns stage only missing distributions; conflicts require a new source change
and version. Rerun failed publication jobs with their retained artifacts to
complete a partial release. Main releases are serialized, and stale plans stop
publication. Registry races fail safely and are checked again on a rerun.

Local builds use `0.1.0+git.<sha>`. A public build receives
`TRAME_VTKJS_RELEASE_VERSION=X.Y.Z` from `release_plan.py`; its sdist preserves
that version and built browser assets without requiring Git or npm at install.
See [build and test](development.md) for non-publishing commands. Release-tool
updates require contract tests and workflow validation. Full MapLibre/recovery
qualification remains separate from CI's headless shared-GL/codec smoke gate.
