"""Sphinx configuration for OptionChainAnalytics documentation."""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / 'src'))

project = 'OptionChainAnalytics'
author = 'Artur Sepp'
copyright = '2026, Artur Sepp'

extensions = ['myst_parser']
source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}
exclude_patterns = ['_build']
html_theme = 'furo'
html_title = 'OptionChainAnalytics documentation'
html_baseurl = 'https://artursepp.github.io/OptionChainAnalytics/'
html_extra_path = ['robots.txt', 'sitemap.xml']
myst_heading_anchors = 3
