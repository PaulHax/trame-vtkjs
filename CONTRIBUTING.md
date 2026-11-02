# Contributing

Create a branch for your change and follow [build and test](docs/development.md).
Install the configured checks with `python -m pip install pre-commit`, then run
`pre-commit install` and `pre-commit run --all-files`.

Use Conventional Commits, such as `feat: add a view option` or
`fix: repair scene recovery`. CI checks the incoming messages, and release-causing
commits select versions when merged to `main`. See [release rules](docs/releases.md).

Open a pull request with a concrete description of the behavior being changed.
