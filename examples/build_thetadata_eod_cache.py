"""Build or resume a normalized ThetaData EOD option cache.

The example is a thin command-line wrapper around OCA's supported provider
API. Existing compatible monthly partitions are skipped automatically.

Examples
--------
Build the free delayed SPY history from June 2023 through yesterday::

    python examples/build_thetadata_eod_cache.py --ticker SPY --start-date 2023-06-01

Load every listed strike instead of the default 20 strikes around spot::

    python examples/build_thetadata_eod_cache.py --ticker SPY --all-strikes
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from option_chain_analytics import build_thetadata_eod_cache, load_thetadata_eod_cache


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


def main() -> None:
    args = _parse_args()
    cache_root = build_thetadata_eod_cache(
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
    options_data = load_thetadata_eod_cache(cache_root)
    print(f'cache={cache_root}')
    print(f'option_rows={len(options_data.chain_ts):,}')
    print(f'eod_observations={len(options_data.get_timeindex()):,}')
    print(f'spot_rows={len(options_data.spot_data):,}')


if __name__ == '__main__':
    main()
