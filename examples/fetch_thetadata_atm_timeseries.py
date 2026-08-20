"""Plot rolling ATM volatility or skew from a local ThetaData EOD cache.

The default SPY workflow reads the cache created by
``build_thetadata_eod_cache.py`` and makes no network request. Pass ``--live``
to fetch the requested date range from ThetaData instead.

The default window is July 2026::

    python examples/fetch_thetadata_atm_timeseries.py --metric atm --output spy_atm.png
    python examples/fetch_thetadata_atm_timeseries.py --metric skew --output spy_skew.png
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from option_chain_analytics import (
    OptionsDataDFs,
    SlicesChain,
    create_chain_timeseries,
    load_thetadata_eod_cache,
    load_thetadata_eod_options_timeseries,
)
from option_chain_analytics import local_path as lp


class LocalTests(Enum):
    """Runnable cases for the ThetaData time-series example."""

    THETADATA_ATM_TIMESERIES = 1


def load_cached_thetadata_chain_timeseries(
    cache_root: str | Path,
    start_date: date | str,
    end_date: date | str,
) -> OptionsDataDFs:
    """Load an inclusive EOD range from a partitioned OCA ThetaData cache."""
    return load_thetadata_eod_cache(
        cache_root=cache_root,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_thetadata_chain_timeseries(
    ticker: str,
    start_date: date | str,
    end_date: date | str,
    *,
    expirations: Sequence[date | str] | None = None,
    min_dte: int = 7,
    max_dte: int = 60,
    strike_range: int | None = 20,
    client: Any | None = None,
) -> OptionsDataDFs:
    """Fetch a date range of EOD chains into OCA's ``OptionsDataDFs``.

    Expirations are fetched only over report dates where their calendar DTE is
    between ``min_dte`` and ``max_dte``. This bounds request size while retaining
    enough overlapping maturities for point-in-time rolling selection.
    """
    mapped = load_thetadata_eod_options_timeseries(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        expirations=expirations,
        min_dte=min_dte,
        max_dte=max_dte,
        strike_range=strike_range,
        client=client,
    )
    options_data = OptionsDataDFs(**mapped)
    if len(options_data.get_timeindex()) == 0:
        raise ValueError('ThetaData reports did not produce any reconstructable OCA chains')
    return options_data


def extract_rolling_atm_vols(
    options_data: OptionsDataDFs,
    *,
    days_before_roll: int = 7,
    delta: float = 0.25,
) -> tuple[dict[pd.Timestamp, SlicesChain], pd.DataFrame]:
    """Reconstruct exact EOD chains and extract rolling ATM vol and delta skew."""
    if days_before_roll < 0:
        raise ValueError('days_before_roll must be non-negative')
    if not 0.0 < delta < 0.5:
        raise ValueError('delta must be strictly between 0 and 0.5')

    observation_times = options_data.get_timeindex()
    chains = create_chain_timeseries(
        options_data=options_data,
        dates_schedule=observation_times,
        time_selection='exact',
    )
    records: dict[pd.Timestamp, dict[str, object]] = {}
    for value_time, chain in chains.items():
        roll_boundary = value_time + pd.Timedelta(days=days_before_roll)
        eligible = [
            (expiry_slice.expiry_time, slice_id)
            for slice_id, expiry_slice in chain.expiry_slices.items()
            if expiry_slice.expiry_time >= roll_boundary
        ]
        if not eligible:
            continue
        expiry_time, slice_id = min(eligible)
        atm_vol = chain.get_atm_vol(slice_id=slice_id)
        if atm_vol is None or not np.isfinite(atm_vol):
            continue
        skew = chain.get_skew(slice_id=slice_id, delta=delta)
        records[value_time] = {
            'atm_vol': float(atm_vol),
            'skew': np.nan if skew is None or not np.isfinite(skew) else float(skew),
            'expiration': expiry_time,
            'dte': (expiry_time - value_time).total_seconds() / (24.0 * 60.0 * 60.0),
        }

    atm_data = pd.DataFrame.from_dict(records, orient='index').sort_index()
    atm_data.index = pd.DatetimeIndex(atm_data.index, name='value_time')
    return chains, atm_data


def plot_atm_vols(atm_data: pd.DataFrame, ticker: str) -> Figure:
    """Plot decimal ATM implied volatilities as percentages."""
    if atm_data.empty:
        raise ValueError('atm_data must not be empty')
    figure, axis = plt.subplots(figsize=(11, 5), tight_layout=True)
    axis.plot(atm_data.index, 100.0 * atm_data['atm_vol'], marker='o', linewidth=1.5)
    axis.set_title(f'{ticker.upper()} rolling ATM implied volatility')
    axis.set_xlabel('ThetaData EOD observation time')
    axis.set_ylabel('ATM implied volatility (%)')
    axis.grid(alpha=0.3)
    figure.autofmt_xdate()
    return figure


def plot_skew(atm_data: pd.DataFrame, ticker: str, *, delta: float = 0.25) -> Figure:
    """Plot OCA delta skew in volatility points per unit log-strike."""
    skew = atm_data['skew'].dropna()
    if skew.empty:
        raise ValueError('atm_data does not contain finite skew observations')
    delta_label = f'{100.0 * delta:g}-delta'
    figure, axis = plt.subplots(figsize=(11, 5), tight_layout=True)
    axis.plot(skew.index, 100.0 * skew, marker='o', linewidth=1.5, color='tab:orange')
    axis.axhline(0.0, color='black', linewidth=0.8, alpha=0.5)
    axis.set_title(f'{ticker.upper()} rolling {delta_label} implied-volatility skew')
    axis.set_xlabel('ThetaData EOD observation time')
    axis.set_ylabel('Call-minus-put IV slope (vol points / log-strike)')
    axis.grid(alpha=0.3)
    figure.autofmt_xdate()
    return figure


def fetch_and_plot_thetadata_atm_vols(
    ticker: str,
    start_date: date | str,
    end_date: date | str,
    *,
    expirations: Sequence[date | str] | None = None,
    min_dte: int = 7,
    max_dte: int = 60,
    strike_range: int | None = 20,
    days_before_roll: int = 7,
    output_path: str | Path | None = None,
    client: Any | None = None,
) -> tuple[OptionsDataDFs, dict[pd.Timestamp, SlicesChain], pd.DataFrame, Figure]:
    """Fetch OCA chain history, extract rolling ATM vols, and create a plot."""
    options_data = fetch_thetadata_chain_timeseries(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        expirations=expirations,
        min_dte=min_dte,
        max_dte=max_dte,
        strike_range=strike_range,
        client=client,
    )
    chains, atm_data = extract_rolling_atm_vols(
        options_data=options_data,
        days_before_roll=days_before_roll,
    )
    figure = plot_atm_vols(atm_data=atm_data, ticker=ticker)
    if output_path is not None:
        figure.savefig(Path(output_path), dpi=160)
    return options_data, chains, atm_data, figure


def fetch_and_plot_thetadata_skew(
    ticker: str,
    start_date: date | str,
    end_date: date | str,
    *,
    expirations: Sequence[date | str] | None = None,
    min_dte: int = 7,
    max_dte: int = 60,
    strike_range: int | None = 20,
    days_before_roll: int = 7,
    delta: float = 0.25,
    output_path: str | Path | None = None,
    client: Any | None = None,
) -> tuple[OptionsDataDFs, dict[pd.Timestamp, SlicesChain], pd.DataFrame, Figure]:
    """Fetch OCA chain history, extract rolling delta skew, and create a plot."""
    options_data = fetch_thetadata_chain_timeseries(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        expirations=expirations,
        min_dte=min_dte,
        max_dte=max_dte,
        strike_range=strike_range,
        client=client,
    )
    chains, atm_data = extract_rolling_atm_vols(
        options_data=options_data,
        days_before_roll=days_before_roll,
        delta=delta,
    )
    figure = plot_skew(atm_data=atm_data, ticker=ticker, delta=delta)
    if output_path is not None:
        figure.savefig(Path(output_path), dpi=160)
    return options_data, chains, atm_data, figure


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='SPY')
    parser.add_argument('--start-date', type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument('--end-date', type=date.fromisoformat, default=date(2026, 7, 31))
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--min-dte', type=int, default=7)
    parser.add_argument('--max-dte', type=int, default=60)
    parser.add_argument('--strike-range', type=int, default=20)
    parser.add_argument('--days-before-roll', type=int, default=7)
    parser.add_argument('--metric', choices=('atm', 'skew'), default='atm')
    parser.add_argument('--delta', type=float, default=0.25)
    parser.add_argument('--output', type=Path)
    return parser.parse_args()


def _run_thetadata_atm_timeseries() -> None:
    """Parse CLI inputs and display or save the selected time-series metric."""
    args = _parse_args()
    if args.live:
        options_data = fetch_thetadata_chain_timeseries(
            ticker=args.ticker,
            start_date=args.start_date,
            end_date=args.end_date,
            min_dte=args.min_dte,
            max_dte=args.max_dte,
            strike_range=args.strike_range,
        )
        mode = 'live'
    else:
        cache_root = args.cache_root or Path(lp.get_cache_path()).joinpath(
            'thetadata_options', args.ticker.lower()
        )
        options_data = load_cached_thetadata_chain_timeseries(
            cache_root=cache_root,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        mode = f'cache:{Path(cache_root).resolve()}'
    chains, atm_data = extract_rolling_atm_vols(
        options_data=options_data,
        days_before_roll=args.days_before_roll,
        delta=args.delta,
    )
    if args.metric == 'atm':
        figure = plot_atm_vols(atm_data=atm_data, ticker=args.ticker)
    else:
        figure = plot_skew(atm_data=atm_data, ticker=args.ticker, delta=args.delta)
    if args.output is not None:
        figure.savefig(args.output, dpi=160)
    print(f'mode={mode}')
    print(f'ticker={options_data.ticker}')
    print(f'oca_chain_observations={len(options_data.get_timeindex())}')
    print(f'reconstructed_chains={len(chains)}')
    print(f'{args.metric}_observations={atm_data[args.metric if args.metric == "skew" else "atm_vol"].notna().sum()}')
    print(atm_data.tail().to_string(float_format=lambda value: f'{value:.6f}'))
    if args.output is None:
        plt.show()
    else:
        print(f'plot={args.output.resolve()}')
        plt.close(figure)


def run_local_test(local_test: LocalTests) -> None:
    """Run one selected local example case."""
    if local_test == LocalTests.THETADATA_ATM_TIMESERIES:
        _run_thetadata_atm_timeseries()
    else:
        raise NotImplementedError(f'unsupported local test: {local_test}')


if __name__ == '__main__':

    run_local_test(local_test=LocalTests.THETADATA_ATM_TIMESERIES)
