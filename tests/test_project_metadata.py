from __future__ import annotations

from pathlib import Path
import re
import runpy
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS_ROOT = 'https://optionchainanalytics.readthedocs.io/en/latest/'
DOCUMENTATION_URL = 'https://optionchainanalytics.readthedocs.io'


def test_release_candidate_metadata_is_aligned() -> None:
    with (REPOSITORY_ROOT / 'pyproject.toml').open('rb') as stream:
        project = tomllib.load(stream)['project']

    citation = (REPOSITORY_ROOT / 'CITATION.cff').read_text(encoding='utf-8')
    changelog = (REPOSITORY_ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')

    assert re.fullmatch(r'\d+\.\d+\.\d+', project['version'])
    assert project['requires-python'] == '>=3.10'
    assert project['license'] == 'MIT'
    optional_dependencies = project['optional-dependencies']
    assert 'fitters' not in optional_dependencies
    assert not any(
        'cvxpy' in requirement.lower()
        for requirements in optional_dependencies.values()
        for requirement in requirements
    )
    assert project['urls']['Documentation'] == DOCUMENTATION_URL
    assert f"version: {project['version']}" in citation
    assert f"## [{project['version']}]" in changelog


def test_documentation_discovery_routes_public_pages_to_read_the_docs(tmp_path, monkeypatch) -> None:
    """Every documentation page keeps a legacy redirect to the canonical host."""
    monkeypatch.setitem(sys.modules, 'tomllib', tomllib)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.delenv('READTHEDOCS_CANONICAL_URL', raising=False)
    conf = runpy.run_path(str(REPOSITORY_ROOT / 'docs/conf.py'))
    assert conf['html_baseurl'] == PUBLIC_DOCS_ROOT
    with (REPOSITORY_ROOT / 'pyproject.toml').open('rb') as stream:
        assert conf['release'] == tomllib.load(stream)['project']['version']
    stable = 'https://optionchainanalytics.readthedocs.io/en/stable/'
    monkeypatch.setenv('READTHEDOCS_CANONICAL_URL', stable)
    assert runpy.run_path(str(REPOSITORY_ROOT / 'docs/conf.py'))['html_baseurl'] == stable

    source = tmp_path / 'rendered'
    output = tmp_path / 'redirects'
    source.mkdir()
    pages = [path.stem + '.html' for path in (REPOSITORY_ROOT / 'docs').glob('*.md')]
    assert 'index.html' in pages
    for page in pages:
        (source / page).write_text('Original documentation content', encoding='utf-8')
    redirect = runpy.run_path(str(REPOSITORY_ROOT / '.github/scripts/build_docs_redirects.py'))
    assert redirect['build_redirects'](source, output, PUBLIC_DOCS_ROOT, '/OptionChainAnalytics/') == len(pages)
    for page in pages:
        document = (output / page).read_text(encoding='utf-8')
        target = PUBLIC_DOCS_ROOT if page == 'index.html' else PUBLIC_DOCS_ROOT + page
        assert f'href="{target}"' in document
        assert 'noindex,follow' in document
        assert 'Original documentation content' not in document
    workflow = (REPOSITORY_ROOT / '.github/workflows/docs.yml').read_text(encoding='utf-8')
    assert 'path: docs/_build/redirects' in workflow


def test_community_health_files_exist() -> None:
    required = {
        'CODE_OF_CONDUCT.md',
        'CONTRIBUTING.md',
        'LICENSE',
        'README.md',
        'SECURITY.md',
        '.github/PULL_REQUEST_TEMPLATE.md',
        '.github/ISSUE_TEMPLATE/bug_report.yml',
        '.github/ISSUE_TEMPLATE/feature_request.yml',
    }
    assert all((REPOSITORY_ROOT / path).is_file() for path in required)
