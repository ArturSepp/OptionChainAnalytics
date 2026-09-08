# Releasing OptionChainAnalytics

Publication is a maintainer-only action. Preparing or merging this repository does not authorize a
tag, GitHub Release, documentation deployment, or package upload.

## Release scope

Publish to PyPI when the accumulated, verified changes are ready. Choose the version from
the complete change set and record it in the changelog. The source tag and uploaded wheel
and source distribution identify the same verified commit. A GitHub Release is optional and,
when created, uses that tag. Read the Docs hosts the documentation; the legacy Pages site
only redirects existing links and is not rebuilt for each package release.

## Candidate verification

Run the test suite in clean Python 3.10 through 3.14 environments. From one clean supported
environment, also run the documentation and distribution gates:

```bash
uv sync --locked --group test
uv run --no-sync pytest -q
uv run --locked --only-group lint ruff check .
uv run --no-sync python examples/first_success.py
uv sync --locked --extra docs
uv run --no-sync python -m sphinx -E -W --keep-going -b html docs docs/_build/html
uv build --sdist --clear --out-dir dist
uv build --wheel dist/*.tar.gz --out-dir dist
uv run --no-project python tools/verify_distribution.py dist
```

Install the built wheel into a separate empty environment and run `examples/first_success.py`
against that installation. Inspect the wheel and source distribution for local data, credentials,
machine paths, and repository-only agent/output files.

## Final-release checklist

1. Confirm SigmaStrats compatibility against the exact candidate API.
2. Confirm `project.version`, `CITATION.cff`, and the dated changelog identify the same release.
3. Repeat every candidate check and inspect installed metadata.
4. Obtain explicit approval to publish.
5. Tag the verified commit `v<version>` and publish the verified artefacts to PyPI. Optionally
   create a GitHub Release from the same tag. Never move a published tag.
6. Verify the PyPI version, hashes, metadata and links, the source tag, and the Read the Docs
   build. Record immutable evidence in the ignored `agents/RELEASE_REPORT.md`.

If publication is interrupted, inspect the files already on PyPI and compare their hashes
with the verified artefacts before retrying. An existing version alone does not prove that
publication completed correctly.

Never rebuild between the final artefact verification and upload, and never include empirical data
in a software release.
