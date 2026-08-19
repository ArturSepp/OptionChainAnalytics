"""Build standardized OCA EOD caches across local option-data providers.

SPX/VIX source files resolve under ``<OCA resource path>/cboe_options`` and
BTC/ETH source files under ``<OCA resource path>/tardis``. Explicit command-line
directories override those centralized defaults without changing package state.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from option_chain_analytics import local_path as lp
from option_chain_analytics.ts_loaders import (
    TARDIS_EOD_HOUR_UTC,
    build_local_cboe_options_cache,
    build_local_tardis_eod_options_cache,
)

CBOE_LOCAL_PATH = f"{lp.get_resource_path()}cboe_options\\"
TARDIS_LOCAL_PATH = f"{lp.get_resource_path()}tardis\\"


def build_local_options_caches(
    *,
    cboe_dir: str | Path,
    tardis_dir: str | Path,
    tickers: Iterable[str] = ('SPX', 'VIX', 'BTC', 'ETH'),
    daily_hour_utc: int = TARDIS_EOD_HOUR_UTC,
    overwrite: bool = False,
) -> dict[str, Path]:
    """Build local EOD caches with one provider-neutral physical schema.

    Parameters
    ----------
    cboe_dir : str or Path
        Directory containing SPX/VIX CBOE source files.
    tardis_dir : str or Path
        Directory containing BTC/ETH Tardis source and spot files.
    tickers : iterable of str, default ("SPX", "VIX", "BTC", "ETH")
        Underlyings whose caches should be built.
    daily_hour_utc : int
        Exact UTC observation hour used for Tardis EOD sampling.
    overwrite : bool, default False
        Whether existing normalized caches may be replaced.

    Returns
    -------
    dict[str, Path]
        Cache path keyed by uppercase ticker.
    """
    cboe_dir = Path(cboe_dir).expanduser().resolve()
    tardis_dir = Path(tardis_dir).expanduser().resolve()
    outputs = {}
    for ticker in tickers:
        ticker = ticker.upper()
        if ticker in ('SPX', 'VIX'):
            output = build_local_cboe_options_cache(
                ticker=ticker,
                local_path=str(cboe_dir),
                overwrite=overwrite,
            )
        elif ticker in ('BTC', 'ETH'):
            output = build_local_tardis_eod_options_cache(
                ticker=ticker,
                local_path=str(tardis_dir),
                daily_hour_utc=daily_hour_utc,
                overwrite=overwrite,
            )
        else:
            raise ValueError(f'unsupported ticker={ticker}')
        outputs[ticker] = output
    return outputs


def _build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser with centralized provider directories."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cboe-dir', type=Path, default=Path(CBOE_LOCAL_PATH))
    parser.add_argument('--tardis-dir', type=Path, default=Path(TARDIS_LOCAL_PATH))
    parser.add_argument(
        '--tickers',
        nargs='+',
        choices=('SPX', 'VIX', 'BTC', 'ETH'),
        default=('SPX', 'VIX', 'BTC', 'ETH'),
    )
    parser.add_argument('--daily-hour-utc', type=int, default=TARDIS_EOD_HOUR_UTC)
    parser.add_argument('--overwrite', action='store_true')
    return parser


def main() -> None:
    """Build the requested provider caches and print their paths and sizes."""
    args = _build_parser().parse_args()
    outputs = build_local_options_caches(
        cboe_dir=args.cboe_dir,
        tardis_dir=args.tardis_dir,
        tickers=args.tickers,
        daily_hour_utc=args.daily_hour_utc,
        overwrite=args.overwrite,
    )
    for ticker, output in outputs.items():
        print(f'{ticker}={output} ({output.stat().st_size / 1e6:,.1f} MB)')


if __name__ == '__main__':
    main()
