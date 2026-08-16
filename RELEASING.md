# Releasing OptionChainAnalytics

Publication is a maintainer-only action. Preparing or merging this repository does not authorize a
tag, GitHub Release, documentation deployment, or package upload.

## Release target

The approved release target is `2.0.1`. It restores Python 3.10 support and adds deterministic
point-in-time selection plus normalized per-underlying CBOE caches after the `2.0.0` src-layout
release. The tag, GitHub Release, package upload, and Pages deployment must all refer to the same
verified release commit and artefacts.

## Candidate verification

Run the test suite in clean Python 3.10 through 3.14 environments. From one clean supported
environment, also run the documentation and distribution gates:

```bash
python -m pip install -e ".[dev,docs]"
pytest -q
ruff check src tests examples tools docs/conf.py
sphinx-build -W -b html docs docs/_build/html
python examples/first_success.py
python -m build
python tools/verify_distribution.py dist
```

Install the built wheel into a separate empty environment and run `examples/first_success.py`
against that installation. Inspect the wheel and source distribution for local data, credentials,
machine paths, and repository-only agent/output files.

## Final-release checklist

1. Confirm SigmaStrats compatibility against the exact candidate API.
2. Confirm `project.version`, `CITATION.cff`, and the dated changelog identify the same release.
3. Repeat every candidate check and inspect installed metadata.
4. Obtain explicit approval to publish.
5. Tag the verified commit `v2.0.1`, publish the same artefact to PyPI, create the GitHub Release,
   and manually run the Pages workflow.
6. Verify the PyPI README and links, GitHub release/tag, Pages canonical links, `robots.txt`, and
   `sitemap.xml`; record immutable evidence in the ignored `agents/RELEASE_REPORT.md`.

Never rebuild between the final artefact verification and upload, and never include empirical data
in a software release.
