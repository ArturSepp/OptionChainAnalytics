from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS_ROOT = 'https://optionchainanalytics.readthedocs.io/en/latest/'


def test_release_candidate_metadata_is_aligned() -> None:
    with (REPOSITORY_ROOT / 'pyproject.toml').open('rb') as stream:
        project = tomllib.load(stream)['project']

    citation = (REPOSITORY_ROOT / 'CITATION.cff').read_text(encoding='utf-8')
    changelog = (REPOSITORY_ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')

    assert project['version'] == '5.2.0'
    assert project['requires-python'] == '>=3.10'
    assert project['license'] == 'MIT'
    optional_dependencies = project['optional-dependencies']
    assert 'fitters' not in optional_dependencies
    assert not any(
        'cvxpy' in requirement.lower()
        for requirements in optional_dependencies.values()
        for requirement in requirements
    )
    assert project['urls']['Documentation'] == PUBLIC_DOCS_ROOT
    assert f"version: {project['version']}" in citation
    assert f"## {project['version']}" in changelog


def test_documentation_discovery_files_cover_public_pages() -> None:
    namespace = {'site': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    sitemap = ElementTree.parse(REPOSITORY_ROOT / 'docs' / 'sitemap.xml')
    locations = {node.text for node in sitemap.findall('site:url/site:loc', namespace)}
    expected = {
        f'{PUBLIC_DOCS_ROOT}{source.stem}.html'
        for source in (REPOSITORY_ROOT / 'docs').glob('*.md')
    }

    robots = (REPOSITORY_ROOT / 'docs' / 'robots.txt').read_text(encoding='utf-8')
    assert locations == expected
    assert f'Sitemap: {PUBLIC_DOCS_ROOT}sitemap.xml' in robots


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
