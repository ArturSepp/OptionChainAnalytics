"""Sphinx configuration for OptionChainAnalytics documentation."""

import os
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 metadata tests use the compatible parser.
    import tomli as tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / 'src'))

project = 'option-chain-analytics'
author = 'Artur Sepp'
copyright = '2026, Artur Sepp'
release = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
version = ".".join(release.split(".")[:2])

extensions = ['myst_parser']
source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}
exclude_patterns = ['_build']
# _templates/base.html titles pages other than the homepage "<page title> - option-chain-analytics".
templates_path = ['_templates']
html_theme = 'furo'
html_title = 'option-chain-analytics - point-in-time option-chain data and queries'


def _consolidate_stable(url: str) -> str:
    """Return the canonical base URL with the moving ``stable`` alias replaced by ``latest``.

    Read the Docs builds ``stable`` from the newest release tag and ``latest`` from ``main``, so both
    serve the same pages. Left alone, each copy names itself canonical and search engines see every
    page twice. Numbered versions keep their own canonical URL.
    """
    return re.sub(r'(\.readthedocs\.io/en/)stable(/|$)', r'\1latest\2', url)


html_baseurl = _consolidate_stable(
    os.environ.get("READTHEDOCS_CANONICAL_URL")
    or "https://optionchainanalytics.readthedocs.io/en/latest/"
)
myst_html_meta = {
    'google-site-verification': 'cddUZk3Gsd1MySw42Rwuq_rMzUDcMNkJWekObx-QS9Y',
}
myst_heading_anchors = 3


def _use_root_canonical(app, pagename, templatename, context, doctree) -> None:
    """Use the site root, rather than ``index.html``, as the homepage canonical URL."""
    if pagename == 'index':
        context['pageurl'] = app.config.html_baseurl


def setup(app) -> None:
    """Register documentation build hooks."""
    app.connect('html-page-context', _use_root_canonical)
