"""Generate the deterministic option time-series figures embedded in ``README.md``.

The documentation must remain reproducible without a ThetaData subscription or
redistribution of licensed observations. This script therefore creates a synthetic
point-in-time option panel with OCA's public simulator, reconstructs each daily chain,
applies the same seven-day maturity-roll rule used in the ThetaData tutorial, and
writes the two resulting figures to ``docs/_static/readme``.

Run from the repository root with::

    python tools/generate_readme_figures.py

No network access, local settings, or random generator is used.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from option_chain_analytics import (
    OptionsDataDFs,
    create_chain_timeseries,
    generate_simulated_options_data,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = REPOSITORY_ROOT / 'docs' / '_static' / 'readme'


def build_simulated_options_history() -> OptionsDataDFs:
    """Create a deterministic daily history with changing volatility and skew.

    Each observation is generated independently using only information assigned to
    that date. Combining the observations produces the same long-form schema as a
    normalized provider cache without introducing a rolling estimate or look-ahead.

    Returns
    -------
    OptionsDataDFs
        Synthetic EOD observations and aligned spot prices for ``SYNTH``.
    """
    value_times = pd.date_range(
        start='2026-01-05 21:00:00',
        periods=42,
        freq='B',
        tz='UTC',
    )
    expiries = pd.date_range(
        start='2026-01-09 21:00:00',
        end='2026-04-17 21:00:00',
        freq='7D',
        tz='UTC',
    )
    day_number = np.arange(len(value_times), dtype=float)
    spot_prices = 100.0 * np.exp(
        0.0009 * day_number
        + 0.018 * np.sin(day_number / 4.8)
        - 0.009 * np.cos(day_number / 8.0)
    )

    panels: list[pd.DataFrame] = []
    spots: list[pd.DataFrame] = []
    for index, (value_time, spot_price) in enumerate(zip(value_times, spot_prices)):
        base_vol = 0.225 + 0.018 * np.sin(index / 5.2) + 0.010 * np.cos(index / 2.8)
        skew = -0.22 - 0.045 * np.sin(index / 6.5) + 0.018 * np.cos(index / 3.7)
        daily_data = generate_simulated_options_data(
            ticker='SYNTH',
            value_times=(value_time,),
            expiries=expiries,
            spot_prices=(float(spot_price),),
            strike_multipliers=np.linspace(0.72, 1.28, 17),
            base_vol=float(base_vol),
            skew=float(skew),
            term_slope=0.035,
        )
        panels.append(daily_data.chain_ts)
        spots.append(daily_data.spot_data)

    chain_ts = pd.concat(panels, ignore_index=True)
    chain_ts.attrs['source'] = 'deterministic_simulation'
    spot_data = pd.concat(spots).sort_index()
    spot_data.attrs['source'] = 'deterministic_simulation'
    return OptionsDataDFs(chain_ts=chain_ts, spot_data=spot_data, ticker='SYNTH')


def extract_rolling_metrics(
    options_data: OptionsDataDFs,
    *,
    days_before_roll: int = 7,
    delta: float = 0.25,
) -> pd.DataFrame:
    """Extract ATM volatility and delta skew using a point-in-time maturity roll.

    Parameters
    ----------
    options_data : OptionsDataDFs
        Provider-normalized or simulated option observations.
    days_before_roll : int, default 7
        Minimum calendar days from observation time to selected expiration.
    delta : float, default 0.25
        Absolute call and put delta used for the skew calculation.

    Returns
    -------
    pandas.DataFrame
        ATM volatility, skew, selected expiration, and DTE by observation time.
    """
    chains = create_chain_timeseries(
        options_data=options_data,
        dates_schedule=options_data.get_timeindex(),
        time_selection='exact',
    )
    records = []
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
        skew = chain.get_skew(slice_id=slice_id, delta=delta)
        if atm_vol is None or not np.isfinite(atm_vol):
            continue
        records.append(
            {
                'value_time': value_time,
                'expiration': expiry_time,
                'dte': (expiry_time - value_time).total_seconds() / 86_400.0,
                'atm_vol': float(atm_vol),
                'skew': np.nan if skew is None or not np.isfinite(skew) else float(skew),
            }
        )

    metrics = pd.DataFrame(records).set_index('value_time').sort_index()
    if metrics.empty:
        raise RuntimeError('the simulated history produced no eligible rolling expiries')
    return metrics


def _format_time_axis(figure: Figure) -> None:
    """Apply the shared date-axis formatting used by both README figures."""
    axis = figure.axes[0]
    axis.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
    axis.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    figure.autofmt_xdate(rotation=0, ha='center')


def plot_atm_volatility(metrics: pd.DataFrame) -> Figure:
    """Plot rolling ATM implied volatility from the extracted metric table."""
    figure, axis = plt.subplots(figsize=(10.5, 4.6), layout='constrained')
    axis.plot(
        metrics.index,
        100.0 * metrics['atm_vol'],
        color='#1f77b4',
        marker='o',
        markersize=3.5,
        linewidth=1.8,
        label='Nearest expiry with DTE ≥ 7',
    )
    axis.set_title('Illustrative rolling ATM implied volatility', loc='left', weight='bold')
    axis.set_xlabel('Synthetic EOD observation date')
    axis.set_ylabel('ATM implied volatility (%)')
    axis.grid(axis='y', alpha=0.25)
    axis.spines[['top', 'right']].set_visible(False)
    axis.legend(frameon=False, loc='best')
    _format_time_axis(figure)
    return figure


def plot_delta_skew(metrics: pd.DataFrame, *, delta: float = 0.25) -> Figure:
    """Plot rolling call-minus-put implied-volatility skew from OCA chains."""
    skew = metrics['skew'].dropna()
    figure, axis = plt.subplots(figsize=(10.5, 4.6), layout='constrained')
    axis.plot(
        skew.index,
        100.0 * skew,
        color='#d97706',
        marker='o',
        markersize=3.5,
        linewidth=1.8,
        label=f'{100.0 * delta:g}-delta call-minus-put slope',
    )
    axis.set_title('Illustrative rolling 25-delta implied-volatility skew', loc='left', weight='bold')
    axis.set_xlabel('Synthetic EOD observation date')
    axis.set_ylabel('Skew (vol points / log-strike)')
    axis.grid(axis='y', alpha=0.25)
    axis.spines[['top', 'right']].set_visible(False)
    axis.legend(frameon=False, loc='best')
    _format_time_axis(figure)
    return figure


def generate_readme_figures(output_directory: Path = OUTPUT_DIRECTORY) -> tuple[Path, Path]:
    """Generate and save both deterministic README chart assets.

    Parameters
    ----------
    output_directory : pathlib.Path, default ``OUTPUT_DIRECTORY``
        Destination for the PNG assets.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path]
        ATM-volatility and skew image paths, respectively.
    """
    options_data = build_simulated_options_history()
    metrics = extract_rolling_metrics(options_data)
    output_directory.mkdir(parents=True, exist_ok=True)

    atm_path = output_directory / 'rolling_atm_volatility.png'
    skew_path = output_directory / 'rolling_25d_skew.png'
    with plt.rc_context({'font.size': 10.5, 'figure.facecolor': 'white', 'axes.facecolor': 'white'}):
        atm_figure = plot_atm_volatility(metrics)
        atm_figure.savefig(atm_path, dpi=160, facecolor='white', metadata={'Software': 'OCA'})
        plt.close(atm_figure)

        skew_figure = plot_delta_skew(metrics)
        skew_figure.savefig(skew_path, dpi=160, facecolor='white', metadata={'Software': 'OCA'})
        plt.close(skew_figure)
    return atm_path, skew_path


if __name__ == '__main__':
    generated_paths = generate_readme_figures()
    for generated_path in generated_paths:
        print(generated_path)
