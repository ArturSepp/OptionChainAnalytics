"""Display ATM volatility or delta skew from a ThetaData EOD option chain.

The default path uses a synthetic deterministic injected client and needs no
credentials or network. Pass ``--live`` after installing
``option-chain-analytics[thetadata]`` and configuring the official ThetaData
client's authentication. A live query requires a ticker, historical report
date, and option expiration::

    python examples/fetch_thetadata_eod.py
    python examples/fetch_thetadata_eod.py --live --ticker AAPL --value-date 2026-07-24 --expiration 2026-08-21 --metric both
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Literal

import pandas as pd
import vanilla_option_pricers as bsm

from option_chain_analytics import (
    OptionsDataDFs,
    SliceColumn,
    create_chain_at_time,
    load_thetadata_eod_options_data,
)


class Locals(Enum):
    """Runnable cases for the single-date ThetaData example."""

    THETADATA_EOD = 1


@dataclass
class OfflineThetaDataClient:
    value_date: date = date(2026, 8, 17)
    expiration: date = date(2026, 9, 18)

    def option_list_expirations(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame({'expiration': [self.expiration]})

    def option_history_eod(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        expiration: date,
    ) -> pd.DataFrame:
        report_time = pd.Timestamp(f'{self.value_date} 17:15:00', tz='America/New_York')
        expiry_time = pd.Timestamp(f'{expiration} 16:00:00', tz='America/New_York')
        ttm = (expiry_time - report_time).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
        forward, discount, volatility = 102.0, 0.995, 0.25
        rows = []
        for strike in (95.0, 100.0, 105.0):
            for right, option_type in (('CALL', 'C'), ('PUT', 'P')):
                mark = bsm.compute_bsm_vanilla_price(
                    ttm=ttm,
                    forward=forward,
                    strike=strike,
                    optiontype=option_type,
                    vol=volatility,
                    discfactor=discount,
                )
                rows.append(
                    {
                        'symbol': symbol,
                        'expiration': expiration,
                        'strike': strike,
                        'right': right,
                        'created': report_time,
                        'volume': 10,
                        'bid_size': 5,
                        'bid': mark - 0.01,
                        'ask_size': 6,
                        'ask': mark + 0.01,
                    }
                )
        return pd.DataFrame(rows)

    def stock_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        report_time = pd.Timestamp(f'{self.value_date} 17:10:00', tz='America/New_York')
        return pd.DataFrame({'created': [report_time], 'close': [100.0]})

    def interest_rate_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        report_time = pd.Timestamp(f'{self.value_date} 17:15:00', tz='America/New_York')
        expiry_time = pd.Timestamp(f'{self.expiration} 16:00:00', tz='America/New_York')
        ttm = (expiry_time - report_time).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
        rate_percent = -100.0 * math.log(0.995) / ttm
        return pd.DataFrame({'created': [self.value_date], 'rate': [rate_percent]})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Use the authenticated ThetaData client.')
    parser.add_argument('--ticker', default='DEMO', help='US equity or ETF option root.')
    parser.add_argument(
        '--value-date',
        type=date.fromisoformat,
        default=date(2026, 8, 17),
        help='Historical EOD report date in YYYY-MM-DD form.',
    )
    parser.add_argument(
        '--expiration',
        type=date.fromisoformat,
        default=date(2026, 9, 18),
        help='Option expiration in YYYY-MM-DD form.',
    )
    parser.add_argument(
        '--metric',
        choices=('atm', 'skew', 'both'),
        default='both',
        help='Metric to display (default: both).',
    )
    parser.add_argument(
        '--delta',
        type=float,
        default=0.25,
        help='Absolute call/put delta used for skew (default: 0.25).',
    )
    args = parser.parse_args()
    if not 0.0 < args.delta < 0.5:
        parser.error('--delta must be strictly between 0 and 0.5')
    return args


def display_thetadata_eod_metrics(
    ticker: str,
    value_date: date | str,
    expiration: date | str,
    *,
    metric: Literal['atm', 'skew', 'both'] = 'both',
    delta: float = 0.25,
    is_live: bool = True,
) -> dict[str, object]:
    """Fetch, display, and return ATM volatility or delta skew.

    Parameters
    ----------
    ticker : str
        US equity or ETF option root, for example ``'AAPL'``.
    value_date : date or str
        Historical EOD report date.
    expiration : date or str
        Option expiration; ATM volatility and skew are maturity-specific.
    metric : {'atm', 'skew', 'both'}, default 'both'
        Metric printed by the function.
    delta : float, default 0.25
        Absolute call and put delta used for the skew calculation.
    is_live : bool, default True
        Use the authenticated official ThetaData client. Set to ``False`` only
        for the deterministic credential-free demonstration.

    Returns
    -------
    dict
        Chain metadata and the requested numeric metrics. Missing metrics are
        returned as ``None``.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError('ticker must not be empty')
    if metric not in ('atm', 'skew', 'both'):
        raise ValueError("metric must be 'atm', 'skew', or 'both'")
    if not 0.0 < delta < 0.5:
        raise ValueError('delta must be strictly between 0 and 0.5')

    report_date = pd.Timestamp(value_date).date()
    expiry_date = pd.Timestamp(expiration).date()
    client = None if is_live else OfflineThetaDataClient(report_date, expiry_date)
    mapped = load_thetadata_eod_options_data(
        ticker=ticker,
        value_date=report_date,
        expirations=[expiry_date],
        client=client,
    )
    options_data = OptionsDataDFs(**mapped)
    value_time = options_data.get_timeindex()[0]
    chain = create_chain_at_time(options_data=options_data, value_time=value_time)
    if chain is None:
        raise RuntimeError('ThetaData normalization did not produce a reconstructable chain')

    slice_id, first_expiry = next(iter(chain.expiry_slices.items()))
    frame = first_expiry.options_df
    atm_vol = chain.get_atm_vol(slice_id=slice_id) if metric in ('atm', 'both') else None
    skew = chain.get_skew(slice_id=slice_id, delta=delta) if metric in ('skew', 'both') else None
    forward = float(frame[SliceColumn.FORWARD_PRICE.value].iloc[0])
    discount = float(frame[SliceColumn.DISCOUNT.value].iloc[0])

    skew_value = None if skew is None or not pd.notna(skew) else float(skew)
    if skew_value is not None and abs(skew_value) < 5e-12:
        skew_value = 0.0
    result = {
        'mode': 'live' if is_live else 'offline',
        'ticker': options_data.ticker,
        'value_time': value_time,
        'expiration': expiry_date,
        'contracts': len(chain.options_df),
        'forward': forward,
        'discount': discount,
        'atm_vol': None if atm_vol is None or not pd.notna(atm_vol) else float(atm_vol),
        'skew': skew_value,
        'delta': delta,
    }

    print(f'mode={result["mode"]}')
    print(f'ticker={options_data.ticker}')
    print(f'value_time={value_time}')
    print(f'expiration={expiry_date}')
    print(f'contracts={len(chain.options_df)}')
    print(f'forward={forward:.6f}')
    print(f'discount={discount:.6f}')

    if metric in ('atm', 'both'):
        if result['atm_vol'] is None:
            print('atm_vol=unavailable')
        else:
            print(f'atm_vol={result["atm_vol"]:.6f} ({100.0 * result["atm_vol"]:.4f}%)')

    if metric in ('skew', 'both'):
        delta_label = f'{100.0 * delta:g}d'
        if result['skew'] is None:
            print(f'skew_{delta_label}=unavailable')
        else:
            print(f'skew_{delta_label}={result["skew"]:.6f}')

    return result


def _run_thetadata_eod() -> None:
    """Parse CLI inputs and display the requested ThetaData EOD metrics."""
    args = _parse_args()
    display_thetadata_eod_metrics(
        ticker=args.ticker,
        value_date=args.value_date,
        expiration=args.expiration,
        metric=args.metric,
        delta=args.delta,
        is_live=args.live,
    )


def run_local(local: Locals) -> None:
    """Run one selected local example case."""
    if local == Locals.THETADATA_EOD:
        _run_thetadata_eod()
    else:
        raise NotImplementedError(f'unsupported local: {local}')


if __name__ == '__main__':

    run_local(local=Locals.THETADATA_EOD)
