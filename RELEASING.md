# Releases

The release workflow uses Python Semantic Release's Conventional Commit parser and version algorithm, following the [trame-vtklocal release toolchain](https://github.com/Kitware/trame-vtklocal/blob/9fe5dc789d6ae8b1ea4b6392869cdd1931ee5e4a/.github/workflows/test_and_release.yml). The bridge builds distributions before qualification and publishes those exact artifacts.

## Commits and versions

CI validates every incoming non-merge commit. Use Conventional Commits, including a short scope when useful:

- `feat: add a view option` selects a minor release.
- `fix: repair scene recovery` and `perf: reduce array copies` select patch releases.
- `docs:`, `chore:`, `ci:`, `build:`, `test:`, `style:` and ordinary `refactor:` changes validate and test without publishing.
- A `!` after the type/scope, or a `BREAKING CHANGE:` footer, selects a breaking release. Before 1.0 this increments the minor version; at 1.0 and later it increments the major version.

Rebase merging preserves the validated commit messages. If squash merging is used, its final commit message must also follow these rules. To check a message locally, install `requirements-release.txt` and run `python release_plan.py lint --message-file PATH`.

The first independent release is `0.1.0`. Its tags use `trame-vtkjs-v{version}` so retained tags from the previous product identity cannot select a version. The product baseline in `pyproject.toml` excludes inherited commits from semantic calculation and initial message validation. Later versions are calculated from product tags; maintainers do not edit a version file or create a release commit. Exact source provenance lives in the wheel's `build-info.json`.

## Build, qualify and publish

Pull requests and `main` pushes run commit validation, JavaScript tests, a clean locked browser build, package checks, installed-wheel Python tests, and headless shared-GL/worker/codec browser tests. A full MapLibre and replication qualification remains separate from this smoke gate.

For release-causing `main` changes, the workflow records a source-bound semantic plan before building a public-version wheel and sdist. It verifies that both distributions contain identical Python, facade and runtime asset files. It retains their hashes, source/tree, upstream pins and browser bundle hash in release evidence.

The GitHub publication job downloads the tested artifacts, refreshes tags and rechecks the plan and bytes. A newer untagged `main` supersedes a queued older release. The job creates a stable GitHub release with the wheel, sdist and evidence. The separate PyPI job downloads those artifacts, checks existing registry digests, stages only missing distributions, and uses trusted publishing. It does not check out or rebuild source. No publication job runs for pull requests or outside `PaulHax/trame-vtkjs` on `main`.

Local `./release.sh build` creates a development version such as `0.1.0+git.<sha>`. `./release.sh verify` checks the saved artifacts without rebuilding or uploading. A public build sets `TRAME_VTKJS_RELEASE_VERSION=X.Y.Z` from `python release_plan.py plan --output dist/release-plan.json`. The build and publication commands require committed source. A source distribution retains its version and built assets, allowing installation without Git or npm.

## First repository and publisher setup

Create the independent repository with shipping ancestry and default branch `main`. Preserve the old repository, its tags and release assets so previously pinned URLs remain installable. Keep Actions disabled during staging unless the initial push is intended to publish. No repository or registry is created by the workflow configuration itself.

Before enabling publication, configure these matching fields in PyPI's [pending trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) or the existing project's publisher settings:

| Field | Value |
| --- | --- |
| PyPI project | `trame-vtkjs` |
| Publisher | GitHub Actions |
| Repository owner | `PaulHax` |
| Repository | `trame-vtkjs` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Create the matching `pypi` environment in GitHub and allow releases from `main`. Configure branch protection and merge settings to preserve validated conventional messages. The build jobs have read-only repository access; only the GitHub release job has `contents: write`, and only the isolated PyPI job has `id-token: write`. No long-lived PyPI token is used. See [PyPI's trusted publishing instructions](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

Python Semantic Release and GitPython are pinned in `requirements-release.txt`. The PyPA publishing action is pinned to an inspected commit. Updating either toolchain requires the release contract tests and workflow validation.

## Reruns and recovery

The same tested wheel and sdist can be published again only when existing bytes match. Differing GitHub assets or PyPI digests stop publication before missing files are uploaded. `skip-existing` and asset clobbering are not used. If the version's bytes differ, use a new source change and version.

A partial publication can be completed by rerunning the original workflow with its retained artifacts. A product tag already attached to that exact source is accepted for recovery. The plan, source and hashes are checked again; no rebuild is performed in either publication job. Concurrent main releases are serialized. If registry state changes between preflight and upload, the upload fails safely and a rerun compares that state again.

After publication, downstream integrations must lock the actual published artifact and verify its embedded revisions. Keep streaming-package replacements in a separate bridge release and downstream pin update.
