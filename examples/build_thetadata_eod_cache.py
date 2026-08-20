"""Build or resume normalized ThetaData EOD options data.

The callable example and its command-line wrapper use OCA's supported provider
API. They require the official ThetaData client and account authentication.
Existing compatible monthly partitions are skipped automatically, so an
interrupted backfill can be resumed without re-requesting completed months.
The partitions are a storage detail: the callable returns one continuous
``OptionsDataDFs`` instance containing the complete requested history.

Examples
--------
Build the free delayed SPY history from June 2023 through yesterday::

    python examples/build_thetadata_eod_cache.py --ticker SPY --start-date 2023-06-01

Load every listed strike instead of the default 20 strikes around spot::

    python examples/build_thetadata_eod_cache.py --ticker SPY --all-strikes

Use the same workflow from Python::

    from examples.build_thetadata_eod_cache import create_thetadata_options_data

    options_data = create_thetadata_options_data(
        ticker='TLT',
        start_date='2023-06-01',
        end_date='2023-06-30',
    )

The output is written under ``$OCA_CACHE_PATH/thetadata_options/<ticker>/`` by
default. Raw responses and credentials are not stored by OCA.
"""

from __future__ import annotations

import argparse
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from option_chain_analytics import (
    OptionsDataDFs,
    build_thetadata_eod_cache,
    load_thetadata_eod_cache,
)
from option_chain_analytics import local_path as lp


class LocalTests(Enum):
    """Runnable cases for the ThetaData cache-building example."""

    BUILD_THETADATA_EOD_CACHE = 1


def create_thetadata_options_data(
    ticker: str = 'SPY',
    start_date: date | str = date(2023, 6, 1),
    end_date: date | str | None = None,
    *,
    output_dir: str | Path | None = None,
    min_dte: int = 0,
    max_dte: int = 60,
    strike_range: int | None = 20,
    liquidity_threshold: float = 1.0,
    overwrite: bool = False,
    client: Any | None = None,
) -> OptionsDataDFs:
    """Build or resume a ThetaData cache and return one complete OCA container.

    Monthly Parquet files make long downloads resumable and bounded reads
    efficient. They do not split the research interface: this function loads
    all completed partitions into one continuous :class:`OptionsDataDFs`.

    Parameters mirror :func:`option_chain_analytics.build_thetadata_eod_cache`.
    ``client`` supports an injected ThetaData-compatible client, which is
    useful for deterministic tests; normal use leaves it unset.
    """
    cache_root = build_thetadata_eod_cache(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        min_dte=min_dte,
        max_dte=max_dte,
        strike_range=strike_range,
        liquidity_threshold=liquidity_threshold,
        overwrite=overwrite,
        client=client,
    )
    return load_thetadata_eod_cache(cache_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='SPY')
    parser.add_argument('--start-date', type=date.fromisoformat, default=date(2023, 6, 1))
    parser.add_argument('--end-date', type=date.fromisoformat)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--min-dte', type=int, default=0)
    parser.add_argument('--max-dte', type=int, default=60)
    parser.add_argument('--strike-range', type=int, default=20)
    parser.add_argument('--all-strikes', action='store_true')
    parser.add_argument('--liquidity-threshold', type=float, default=1.0)
    parser.add_argument('--overwrite', action='store_true')
    return parser.parse_args()


def _run_build_thetadata_eod_cache() -> None:
    """Parse CLI inputs, build the cache, and print its dimensions."""
    args = _parse_args()
    cache_root = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else Path(lp.get_cache_path())
        .joinpath('thetadata_options', args.ticker.strip().lower())
        .resolve()
    )
    options_data = create_thetadata_options_data(
        ticker=args.ticker,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        strike_range=None if args.all_strikes else args.strike_range,
        liquidity_threshold=args.liquidity_threshold,
        overwrite=args.overwrite,
    )
    print(f'cache={cache_root}')
    print(f'option_rows={len(options_data.chain_ts):,}')
    print(f'eod_observations={len(options_data.get_timeindex()):,}')
    print(f'spot_rows={len(options_data.spot_data):,}')


def run_local_test(local_test: LocalTests) -> None:
    """Run one selected local example case."""
    if local_test == LocalTests.BUILD_THETADATA_EOD_CACHE:
        _run_build_thetadata_eod_cache()
    else:
        raise NotImplementedError(f'unsupported local test: {local_test}')


if __name__ == '__main__':

    run_local_test(local_test=LocalTests.BUILD_THETADATA_EOD_CACHE)
