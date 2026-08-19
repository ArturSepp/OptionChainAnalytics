"""Build normalized Parquet caches for local SPX and VIX CBOE datasets.

The default input directory is ``<OCA resource path>/cboe_options``. Pass
``--data-dir`` to use another directory; source data and generated caches remain
local and are never included in the OCA distribution.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from option_chain_analytics import local_path as lp
from option_chain_analytics.ts_loaders import build_local_cboe_options_cache

CBOE_LOCAL_PATH = f"{lp.get_resource_path()}cboe_options\\"


def build_cboe_research_caches(
    data_dir: str | Path,
    *,
    tickers: Iterable[str] = ('SPX', 'VIX'),
    overwrite: bool = False,
) -> dict[str, Path]:
    """Convert local consolidated CBOE datasets into reusable OCA caches.

    Parameters
    ----------
    data_dir : str or Path
        Directory containing the per-underlying CBOE source files.
    tickers : iterable of str, default ("SPX", "VIX")
        Underlyings whose caches should be built.
    overwrite : bool, default False
        Whether existing normalized caches may be replaced.

    Returns
    -------
    dict[str, Path]
        Cache path keyed by uppercase ticker.
    """
    data_dir = Path(data_dir).expanduser().resolve()
    outputs = {}
    for ticker in tickers:
        ticker = ticker.upper()
        outputs[ticker] = build_local_cboe_options_cache(
            ticker=ticker,
            local_path=str(data_dir),
            overwrite=overwrite,
        )
    return outputs


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser with centralized local-data defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(CBOE_LOCAL_PATH))
    parser.add_argument('--tickers', nargs='+', choices=('SPX', 'VIX'), default=('SPX', 'VIX'))
    parser.add_argument('--overwrite', action='store_true')
    return parser


def main() -> None:
    """Build the requested caches and print their paths and sizes."""
    args = _build_parser().parse_args()
    outputs = build_cboe_research_caches(
        data_dir=args.data_dir,
        tickers=args.tickers,
        overwrite=args.overwrite,
    )
    for ticker, output in outputs.items():
        print(f'{ticker}={output} ({output.stat().st_size / 1e6:,.1f} MB)')


if __name__ == '__main__':
    main()
