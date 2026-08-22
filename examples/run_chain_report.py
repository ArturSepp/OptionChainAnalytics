"""Create a multi-expiry PDF report from a local ThetaData EOD cache.

The default reads SPY on 17 July 2026 without making a network request. Build
the cache first, then select an output path::

    python examples/run_chain_report.py --date 2026-07-17 --output spy_chain_report.pdf

Use ``--ticker`` and ``--cache-root`` for another cached equity or ETF.
"""

from __future__ import annotations

import argparse
from datetime import date
from enum import Enum
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from option_chain_analytics import (
    create_chain_at_time,
    load_thetadata_eod_cache,
    run_chain_report,
)
from option_chain_analytics import local_path as lp


class Locals(Enum):
    """Runnable cases for the cached chain-report example."""

    CHAIN_REPORT = 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='SPY')
    parser.add_argument('--date', type=date.fromisoformat, default=date(2026, 7, 17))
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--output', type=Path)
    return parser.parse_args()


def _run_chain_report() -> None:
    """Load the selected cached chain and display or save its report."""
    args = _parse_args()
    cache_root = args.cache_root or Path(lp.get_cache_path()).joinpath(
        'thetadata_options', args.ticker.lower()
    )
    options_data = load_thetadata_eod_cache(
        cache_root,
        start_date=args.date,
        end_date=args.date,
    )
    value_time = pd.Timestamp(options_data.get_timeindex()[0])
    chain = create_chain_at_time(options_data, value_time=value_time)
    if chain is None:
        raise RuntimeError(f'no exact OCA chain available for {args.date}')
    figures = run_chain_report(chain=chain)
    print(f'ticker={options_data.ticker}')
    print(f'value_time={value_time}')
    print(f'expirations={len(chain.expiry_slices)}')
    print(f'contracts={len(chain.options_df)}')
    if args.output is None:
        plt.show()
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with PdfPages(args.output) as pdf:
            for figure in figures.values():
                pdf.savefig(figure)
        print(f'report={args.output.resolve()}')
        plt.close('all')


def run_local(local: Locals) -> None:
    """Run one selected local example case."""
    if local == Locals.CHAIN_REPORT:
        _run_chain_report()
    else:
        raise NotImplementedError(f'unsupported local: {local}')


if __name__ == '__main__':

    run_local(local=Locals.CHAIN_REPORT)
