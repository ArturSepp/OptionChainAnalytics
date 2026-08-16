"""Deterministic simulated option-chain data for examples, tests, and tutorials."""

from collections.abc import Sequence

import numpy as np
import pandas as pd
import vanilla_option_pricers as bsm

from option_chain_analytics.chain_ts import OptionsDataDFs
from option_chain_analytics.option_chain import SliceColumn

DEFAULT_VALUE_TIMES = (
    pd.Timestamp('2024-01-05 08:00:00', tz='UTC'),
    pd.Timestamp('2024-01-12 08:00:00', tz='UTC'),
)
DEFAULT_EXPIRIES = (
    pd.Timestamp('2024-01-12 16:00:00', tz='UTC'),
    pd.Timestamp('2024-01-19 08:00:00', tz='UTC'),
    pd.Timestamp('2024-02-16 08:00:00', tz='UTC'),
)


def _as_utc_index(values: Sequence[pd.Timestamp], name: str) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(values))
    if index.empty:
        raise ValueError(f'{name} must not be empty')
    if index.tz is None:
        index = index.tz_localize('UTC')
    else:
        index = index.tz_convert('UTC')
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f'{name} must be unique and increasing')
    return index


def generate_simulated_options_data(
    ticker: str = 'SYNTH',
    value_times: Sequence[pd.Timestamp] = DEFAULT_VALUE_TIMES,
    expiries: Sequence[pd.Timestamp] = DEFAULT_EXPIRIES,
    spot_prices: Sequence[float] = (100.0, 101.0),
    strike_multipliers: Sequence[float] = (0.8, 0.9, 1.0, 1.1, 1.2),
    base_vol: float = 0.20,
    skew: float = -0.12,
    term_slope: float = 0.04,
    rate: float = 0.02,
    dividend_yield: float = 0.01,
    bid_ask_iv_spread: float = 0.02,
    contract_size: float = 100.0,
) -> OptionsDataDFs:
    """Create a small deterministic panel in the native OCA schema.

    Prices and Greeks use Black-Scholes-Merton on the forward measure. The same
    contracts appear at each observation time, so time to maturity declines
    without introducing future observations. Volatility is a deterministic
    skew-and-term surface; no random generator or network access is used.

    Parameters
    ----------
    ticker : str, default ``'SYNTH'``
        Synthetic underlying identifier.
    value_times : sequence of pandas.Timestamp
        Increasing observation times. Naive values are interpreted as UTC.
    expiries : sequence of pandas.Timestamp
        Contract expiry times. Naive values are interpreted as UTC.
    spot_prices : sequence of float
        Spot price at each observation time.
    strike_multipliers : sequence of float
        Fixed strikes expressed as multiples of the first spot price.
    base_vol, skew, term_slope : float
        Decimal volatility-surface parameters.
    rate, dividend_yield : float
        Continuously compounded annual rates.
    bid_ask_iv_spread : float
        Total decimal implied-volatility spread around the mark.
    contract_size : float
        Units of underlying represented by one contract.

    Returns
    -------
    OptionsDataDFs
        Complete point-in-time option panel and aligned spot series.
    """
    ticker = ticker.upper()
    if not ticker:
        raise ValueError('ticker must not be empty')

    value_index = _as_utc_index(value_times, name='value_times')
    expiry_index = _as_utc_index(expiries, name='expiries')
    spots = np.asarray(spot_prices, dtype=float)
    strike_multipliers_array = np.asarray(strike_multipliers, dtype=float)
    if len(spots) != len(value_index):
        raise ValueError('spot_prices must have one value per observation time')
    if np.any(spots <= 0.0):
        raise ValueError('spot_prices must be positive')
    if np.any(strike_multipliers_array <= 0.0):
        raise ValueError('strike_multipliers must be positive')
    if bid_ask_iv_spread < 0.0:
        raise ValueError('bid_ask_iv_spread must be non-negative')

    strikes = spots[0] * strike_multipliers_array
    rows = []
    for time_idx, (value_time, spot) in enumerate(zip(value_index, spots)):
        for expiry_idx, expiry in enumerate(expiry_index):
            ttm = (expiry - value_time).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
            if ttm <= 0.0:
                continue
            discount = float(np.exp(-rate * ttm))
            forward = float(spot * np.exp((rate - dividend_yield) * ttm))
            maturity_id = expiry.strftime('%d%b%Y')
            for strike_idx, strike in enumerate(strikes):
                log_moneyness = float(np.log(strike / forward))
                mark_iv = max(0.05, base_vol + skew * log_moneyness + term_slope * np.sqrt(ttm))
                bid_iv = max(0.01, mark_iv - 0.5 * bid_ask_iv_spread)
                ask_iv = mark_iv + 0.5 * bid_ask_iv_spread
                open_interest = float(1000 - 100 * abs(strike_idx - 0.5 * (len(strikes) - 1)))
                for option_type in ('C', 'P'):
                    common = dict(
                        forward=forward,
                        strike=float(strike),
                        ttm=ttm,
                        optiontype=option_type,
                        discfactor=discount,
                    )
                    mark_price = bsm.compute_bsm_vanilla_price(vol=mark_iv, **common)
                    bid_price = bsm.compute_bsm_vanilla_price(vol=bid_iv, **common)
                    ask_price = bsm.compute_bsm_vanilla_price(vol=ask_iv, **common)
                    contract = f'{ticker}-{expiry:%Y%m%d}-{option_type}-{strike:g}'
                    rows.append(
                        {
                            SliceColumn.CONTRACT.value: contract,
                            SliceColumn.EXCHANGE_TIME.value: value_time,
                            SliceColumn.UNDERLYING_INDEX.value: ticker,
                            SliceColumn.FORWARD_PRICE.value: forward,
                            SliceColumn.SPOT_PRICE.value: float(spot),
                            SliceColumn.USD_MULTIPLIER.value: 1.0,
                            SliceColumn.MARK_PRICE.value: mark_price,
                            SliceColumn.BID_PRICE.value: bid_price,
                            SliceColumn.ASK_PRICE.value: ask_price,
                            SliceColumn.BID_SIZE.value: float(10 + strike_idx),
                            SliceColumn.ASK_SIZE.value: float(12 + strike_idx),
                            SliceColumn.MARK_IV.value: mark_iv,
                            SliceColumn.BID_IV.value: bid_iv,
                            SliceColumn.ASK_IV.value: ask_iv,
                            SliceColumn.DELTA.value: bsm.compute_bsm_vanilla_delta(vol=mark_iv, **common),
                            SliceColumn.VEGA.value: bsm.compute_bsm_vanilla_vega(
                                ttm=ttm,
                                forward=forward,
                                strike=float(strike),
                                vol=mark_iv,
                                discfactor=discount,
                            ),
                            SliceColumn.THETA.value: bsm.compute_bsm_vanilla_theta(
                                vol=mark_iv,
                                discount_rate=rate,
                                **common,
                            ),
                            SliceColumn.GAMMA.value: bsm.compute_bsm_vanilla_gamma(
                                ttm=ttm,
                                forward=forward,
                                strike=float(strike),
                                vol=mark_iv,
                            ),
                            SliceColumn.OPEN_INTEREST.value: open_interest,
                            SliceColumn.VOLUME.value: float(25 + time_idx + expiry_idx + strike_idx),
                            SliceColumn.MATURITY_ID.value: maturity_id,
                            SliceColumn.STRIKE.value: float(strike),
                            SliceColumn.OPTION_TYPE.value: option_type,
                            SliceColumn.EXPIRY.value: expiry,
                            SliceColumn.TTM.value: ttm,
                            SliceColumn.CONTRACT_SIZE.value: float(contract_size),
                            SliceColumn.DISCOUNT.value: discount,
                        }
                    )

    if not rows:
        raise ValueError('no positive-time-to-maturity contracts were generated')
    chain_ts = pd.DataFrame(rows, columns=[column.value for column in SliceColumn])
    chain_ts.attrs['source'] = 'deterministic_simulation'
    spot_data = pd.DataFrame({'close': spots}, index=value_index)
    spot_data.index.name = SliceColumn.EXCHANGE_TIME.value
    spot_data.attrs['source'] = 'deterministic_simulation'
    return OptionsDataDFs(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)
