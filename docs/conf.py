"""Sphinx configuration for OptionChainAnalytics documentation."""

import os
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
html_theme = 'furo'
html_title = 'option-chain-analytics - point-in-time option-chain data and queries'
html_baseurl = (
    os.environ.get("READTHEDOCS_CANONICAL_URL")
    or "https://optionchainanalytics.readthedocs.io/en/latest/"
)
myst_html_meta = {
    'google-site-verification': 'cddUZk3Gsd1MySw42Rwuq_rMzUDcMNkJWekObx-QS9Y',
}
myst_heading_anchors = 3
