from __future__ import annotations

from pathlib import Path
import re
import runpy
import subprocess
import sys

import pytest

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
    # stable and latest serve the same pages, so both name latest as canonical; numbered versions keep theirs
    stable = 'https://optionchainanalytics.readthedocs.io/en/stable/'
    monkeypatch.setenv('READTHEDOCS_CANONICAL_URL', stable)
    assert runpy.run_path(str(REPOSITORY_ROOT / 'docs/conf.py'))['html_baseurl'] == PUBLIC_DOCS_ROOT
    numbered = 'https://optionchainanalytics.readthedocs.io/en/5.2.1/'
    monkeypatch.setenv('READTHEDOCS_CANONICAL_URL', numbered)
    assert runpy.run_path(str(REPOSITORY_ROOT / 'docs/conf.py'))['html_baseurl'] == numbered

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


def test_documentation_pages_carry_short_titles_and_a_root_homepage_canonical(tmp_path, monkeypatch) -> None:
    """Furo would end every title with the full html_title and canonicalise the homepage as index.html."""
    for module in ('sphinx', 'furo', 'myst_parser'):
        pytest.importorskip(module)
    monkeypatch.delenv('READTHEDOCS_CANONICAL_URL', raising=False)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    conf = runpy.run_path(str(REPOSITORY_ROOT / 'docs/conf.py'))
    templates = [str(REPOSITORY_ROOT / 'docs' / path) for path in conf.get('templates_path', [])]
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'conf.py').write_text(
        'import runpy\n'
        f"_site = runpy.run_path({str(REPOSITORY_ROOT / 'docs/conf.py')!r})\n"
        "extensions = ['myst_parser']\n"
        "html_theme = 'furo'\n"
        f'templates_path = {templates!r}\n'
        "for _key in ('project', 'html_title', 'html_baseurl'):\n"
        '    globals()[_key] = _site[_key]\n'
        "setup = _site.get('setup')\n",
        encoding='utf-8',
    )
    (source / 'index.md').write_text('# Home\n\n```{toctree}\nqueries\n```\n', encoding='utf-8')
    (source / 'queries.md').write_text('# Point-in-time chain queries\n\nText.\n', encoding='utf-8')
    output = tmp_path / 'html'
    result = subprocess.run(
        [sys.executable, '-m', 'sphinx', '-W', '-q', '-b', 'html', str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    def head(name: str) -> str:
        return (output / f'{name}.html').read_text(encoding='utf-8').split('</head>')[0]

    assert re.findall(r'<title>(.*?)</title>', head('index')) == [
        'option-chain-analytics - point-in-time option-chain data and queries'
    ]
    assert re.findall(r'<title>(.*?)</title>', head('queries')) == [
        'Point-in-time chain queries - option-chain-analytics'
    ]
    assert f'<link rel="canonical" href="{PUBLIC_DOCS_ROOT}"' in head('index')
    assert f'<link rel="canonical" href="{PUBLIC_DOCS_ROOT}queries.html"' in head('queries')


def test_documentation_pages_state_a_meta_description() -> None:
    """Every page states, in its MyST front matter, the description that search results show."""
    pages = sorted((REPOSITORY_ROOT / 'docs').glob('*.md'))
    assert pages
    for page in pages:
        text = page.read_text(encoding='utf-8')
        assert text.startswith('---\nmyst:\n  html_meta:\n    description: >-\n'), page.name


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
