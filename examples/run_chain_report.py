"""Create an OCA chain report from the local SPY ThetaData EOD cache."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from option_chain_analytics import (
    create_chain_from_from_options_dfs,
    load_thetadata_eod_cache,
    run_chain_report,
)
from option_chain_analytics import local_path as lp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='SPY')
    parser.add_argument('--date', type=date.fromisoformat, default=date(2026, 7, 17))
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--output', type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cache_root = args.cache_root or Path(lp.get_resource_path()).joinpath(
        'thetadata_options', args.ticker.lower()
    )
    options_data = load_thetadata_eod_cache(
        cache_root,
        start_date=args.date,
        end_date=args.date,
    )
    value_time = pd.Timestamp(options_data.get_timeindex()[0])
    chain = create_chain_from_from_options_dfs(options_data, value_time=value_time)
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


if __name__ == '__main__':
    main()
