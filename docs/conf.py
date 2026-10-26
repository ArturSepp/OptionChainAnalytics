"""Sphinx configuration for OptionChainAnalytics documentation."""

import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

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
myst_enable_extensions = ['dollarmath']
source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}
exclude_patterns = ['_build']
# _templates/base.html titles pages other than the homepage "<page title> - option-chain-analytics".
templates_path = ['_templates']
html_theme = 'furo'
html_title = f'option-chain-analytics {release} - point-in-time option-chain data and queries'


# Each channel describes its own source revision and keeps its canonical URL.
html_baseurl = (
    os.environ.get('READTHEDOCS_CANONICAL_URL') or 'https://optionchainanalytics.readthedocs.io/en/latest/'
)
myst_html_meta = {
    'google-site-verification': 'cddUZk3Gsd1MySw42Rwuq_rMzUDcMNkJWekObx-QS9Y',
}
myst_heading_anchors = 3


def _use_root_canonical(app, pagename, templatename, context, doctree) -> None:
    """Use the site root, rather than ``index.html``, as the homepage canonical URL."""
    if pagename == 'index':
        context['pageurl'] = app.config.html_baseurl



class _CanonicalHead(HTMLParser):
    """Read canonical and indexing metadata from the HTML actually being published."""

    def __init__(self):
        super().__init__()
        self.canonicals = []
        self.noindex = False
        self.redirect = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonicals.append(attributes.get("href"))
        if tag == "meta" and attributes.get("name", "").lower() == "robots":
            self.noindex |= "noindex" in attributes.get("content", "").lower()
        if tag == "meta" and attributes.get("http-equiv", "").lower() == "refresh":
            self.redirect = True


def _write_canonical_sitemap(app, exception) -> None:
    """Offer only rendered, self-canonical pages from this build's own channel."""
    if exception is not None or app.builder.name != "html" or not app.config.html_baseurl:
        return
    base = app.config.html_baseurl.rstrip("/") + "/"
    urls = set()
    for docname in app.env.found_docs:
        head = _CanonicalHead()
        file = Path(app.builder.get_outfilename(docname))
        head.feed(file.read_text(encoding="utf-8").split("</head>")[0])
        if head.noindex or head.redirect or len(head.canonicals) != 1:
            continue
        uri = app.builder.get_target_uri(docname)
        expected = urljoin(base, quote("" if uri == "index.html" else uri, safe="/%"))
        if head.canonicals == [expected]:
            urls.add(expected)
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    root = ElementTree.Element(f"{{{namespace}}}urlset")
    for url in sorted(urls):
        entry = ElementTree.SubElement(root, f"{{{namespace}}}url")
        ElementTree.SubElement(entry, f"{{{namespace}}}loc").text = url
    ElementTree.indent(root)
    ElementTree.ElementTree(root).write(
        Path(app.outdir) / "sitemap.xml", encoding="utf-8", xml_declaration=True,
        default_namespace=namespace,
    )


def setup(app) -> None:
    """Register documentation build hooks."""
    app.connect('html-page-context', _use_root_canonical)
    app.connect("build-finished", _write_canonical_sitemap)
