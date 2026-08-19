"""ThetaData end-of-day equity-option normalization.

The adapter keeps provider access optional and maps ThetaData's national EOD
report into the native :class:`~option_chain_analytics.chain_ts.OptionsDataDFs`
constructor contract.  It supports US equity and ETF options whose contractual
expiry is represented as 16:00 America/New_York.  Index products with AM or
product-specific settlement times are deliberately outside this adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time, timedelta
from typing import Any, Protocol

import numpy as np
import pandas as pd

from option_chain_analytics.fitters.forward_discount import (
    imply_forward_discount_from_bid_ask_prices,
)
from option_chain_analytics.option_chain import SliceColumn

THETADATA_EXPIRY_TIME = time(16, 0)
THETADATA_TIMEZONE = 'America/New_York'
SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

_OPTION_COLUMNS = {
    'symbol',
    'expiration',
    'strike',
    'right',
    'created',
    'volume',
    'bid_size',
    'bid',
    'ask_size',
    'ask',
}
_SPOT_COLUMNS = {'created', 'close'}
_RATE_COLUMNS = {'created', 'rate'}


class ThetaDataClientProtocol(Protocol):
    """Structural subset of the official ThetaData client used by this adapter."""

    def option_list_expirations(self, symbol: str) -> pd.DataFrame: ...

    def option_history_eod(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        expiration: date,
    ) -> pd.DataFrame: ...

    def stock_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame: ...

    def interest_rate_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame: ...


def _empty_spot_data() -> pd.DataFrame:
    index = pd.DatetimeIndex([], tz='UTC', name=SliceColumn.EXCHANGE_TIME.value)
    spot_data = pd.DataFrame({'close': pd.Series(dtype=float)}, index=index)
    spot_data.attrs['source'] = 'thetadata_stock_eod'
    return spot_data


def _normalize_spot_data(source: pd.DataFrame) -> pd.DataFrame:
    if source.empty:
        return _empty_spot_data()
    missing = _SPOT_COLUMNS.difference(source.columns)
    if missing:
        raise ValueError(f'missing ThetaData stock EOD columns: {sorted(missing)}')

    spot_data = source.loc[:, ['created', 'close']].copy()
    spot_data['created'] = pd.to_datetime(spot_data['created'], utc=True, errors='raise')
    spot_data['close'] = pd.to_numeric(spot_data['close'], errors='coerce')
    spot_data = spot_data.dropna(subset=['created', 'close'])
    spot_data = spot_data.loc[spot_data['close'] > 0.0]
    spot_data = spot_data.sort_values('created').drop_duplicates('created', keep='last')
    spot_data = spot_data.set_index('created').rename_axis(SliceColumn.EXCHANGE_TIME.value)
    spot_data.attrs['source'] = 'thetadata_stock_eod'
    return spot_data


def _normalize_rate_data(source: pd.DataFrame | None) -> pd.Series:
    """Normalize ThetaData percentage rates to decimal annual rates by report date."""
    if source is None or source.empty:
        return pd.Series(dtype=float, name='rate')
    missing = _RATE_COLUMNS.difference(source.columns)
    if missing:
        raise ValueError(f'missing ThetaData interest-rate EOD columns: {sorted(missing)}')

    rates = source.loc[:, ['created', 'rate']].copy()
    rates['created'] = pd.to_datetime(rates['created'], errors='raise').dt.date
    rates['rate'] = pd.to_numeric(rates['rate'], errors='coerce') / 100.0
    rates = rates.dropna().sort_values('created').drop_duplicates('created', keep='last')
    rates = rates.set_index('created')['rate']
    rates.attrs['unit'] = 'decimal annual rate'
    return rates


def _discount_from_rate_data(
    rates: pd.Series,
    report_time: pd.Timestamp,
    ttm: float,
) -> float | None:
    if rates.empty or not np.isfinite(ttm) or ttm <= 0.0:
        return None
    report_date = report_time.tz_convert(THETADATA_TIMEZONE).date()
    available = rates.loc[rates.index <= report_date]
    if available.empty or (report_date - available.index[-1]).days > 7:
        return None
    annual_rate = float(available.iloc[-1])
    discount = float(np.exp(-annual_rate * ttm))
    return discount if np.isfinite(discount) and discount > 0.0 else None


def _map_spot_without_look_ahead(
    exchange_time: pd.Series,
    spot_data: pd.DataFrame,
) -> pd.Series:
    if spot_data.empty:
        return pd.Series(np.nan, index=exchange_time.index, dtype=float)

    left = exchange_time.rename(SliceColumn.EXCHANGE_TIME.value).reset_index()
    left = left.sort_values(SliceColumn.EXCHANGE_TIME.value)
    right = spot_data.reset_index().rename(
        columns={SliceColumn.EXCHANGE_TIME.value: 'spot_exchange_time'}
    )
    aligned = pd.merge_asof(
        left,
        right.sort_values('spot_exchange_time'),
        left_on=SliceColumn.EXCHANGE_TIME.value,
        right_on='spot_exchange_time',
        direction='backward',
        allow_exact_matches=True,
    )
    return aligned.set_index('index')['close'].reindex(exchange_time.index)


def _infer_slice_forward_discount(
    frame: pd.DataFrame,
    discount: float | None = None,
) -> tuple[float, float] | None:
    calls = (
        frame.loc[frame[SliceColumn.OPTION_TYPE.value].eq('C')]
        .drop_duplicates(SliceColumn.STRIKE.value)
        .set_index(SliceColumn.STRIKE.value)
    )
    puts = (
        frame.loc[frame[SliceColumn.OPTION_TYPE.value].eq('P')]
        .drop_duplicates(SliceColumn.STRIKE.value)
        .set_index(SliceColumn.STRIKE.value)
    )
    if calls.empty or puts.empty:
        return None

    price_columns = [SliceColumn.BID_PRICE.value, SliceColumn.ASK_PRICE.value]
    result = imply_forward_discount_from_bid_ask_prices(
        calls_bid_ask=calls[price_columns],
        put_bid_ask=puts[price_columns],
        discount=discount,
        discfactor_lower_bound=0.5,
        discfactor_upper_bound=1.5,
    )
    if result is None:
        return None
    forward, discount = map(float, result)
    if not np.isfinite(forward) or not np.isfinite(discount):
        return None
    if forward <= 0.0 or discount <= 0.0:
        return None
    return forward, discount


def _infer_iv_columns(chain_ts: pd.DataFrame) -> None:
    import vanilla_option_pricers as bsm
    from numba.typed import List

    output_by_price = (
        (SliceColumn.BID_IV.value, SliceColumn.BID_PRICE.value),
        (SliceColumn.MARK_IV.value, SliceColumn.MARK_PRICE.value),
        (SliceColumn.ASK_IV.value, SliceColumn.ASK_PRICE.value),
    )
    outputs = {column: np.full(len(chain_ts.index), np.nan) for column, _ in output_by_price}
    grouped = chain_ts.groupby(
        [SliceColumn.EXCHANGE_TIME.value, SliceColumn.MATURITY_ID.value],
        observed=True,
        sort=False,
    )
    for positions in grouped.indices.values():
        frame = chain_ts.iloc[positions]
        ttm = float(frame[SliceColumn.TTM.value].iloc[0])
        forward = float(frame[SliceColumn.FORWARD_PRICE.value].iloc[0])
        discount = float(frame[SliceColumn.DISCOUNT.value].iloc[0])
        if ttm <= 0.0 or forward <= 0.0 or discount <= 0.0:
            continue
        strikes = frame[SliceColumn.STRIKE.value].to_numpy(float)
        option_types = List(frame[SliceColumn.OPTION_TYPE.value].astype(str).tolist())
        for output_column, price_column in output_by_price:
            prices = frame[price_column].to_numpy(float)
            try:
                outputs[output_column][positions] = bsm.infer_bsm_ivols_from_slice_prices(
                    ttm=ttm,
                    forward=forward,
                    discfactor=discount,
                    strikes=strikes,
                    optiontypes=option_types,
                    model_prices=prices,
                )
            except ZeroDivisionError:
                for idx, (strike, option_type, price) in enumerate(
                    zip(strikes, option_types, prices)
                ):
                    try:
                        outputs[output_column][positions[idx]] = bsm.infer_bsm_implied_vol(
                            ttm=ttm,
                            forward=forward,
                            strike=strike,
                            optiontype=str(option_type),
                            given_price=price,
                            discfactor=discount,
                        )
                    except ZeroDivisionError:
                        outputs[output_column][positions[idx]] = np.nan

    for column, values in outputs.items():
        chain_ts[column] = values


def _compute_mark_greeks(chain_ts: pd.DataFrame) -> None:
    import vanilla_option_pricers as bsm

    output_columns = (
        SliceColumn.DELTA.value,
        SliceColumn.VEGA.value,
        SliceColumn.THETA.value,
        SliceColumn.GAMMA.value,
    )
    for column in output_columns:
        chain_ts[column] = np.nan

    for idx, row in chain_ts.iterrows():
        ttm = float(row[SliceColumn.TTM.value])
        forward = float(row[SliceColumn.FORWARD_PRICE.value])
        strike = float(row[SliceColumn.STRIKE.value])
        volatility = float(row[SliceColumn.MARK_IV.value])
        discount = float(row[SliceColumn.DISCOUNT.value])
        if not np.all(np.isfinite([ttm, forward, strike, volatility, discount])):
            continue
        if ttm <= 0.0 or forward <= 0.0 or strike <= 0.0 or volatility <= 0.0 or discount <= 0.0:
            continue
        option_type = str(row[SliceColumn.OPTION_TYPE.value])
        discount_rate = -np.log(discount) / ttm
        common = dict(
            ttm=ttm,
            forward=forward,
            strike=strike,
            vol=volatility,
            optiontype=option_type,
            discfactor=discount,
        )
        chain_ts.at[idx, SliceColumn.DELTA.value] = bsm.compute_bsm_vanilla_delta(**common)
        chain_ts.at[idx, SliceColumn.VEGA.value] = bsm.compute_bsm_vanilla_vega(
            ttm=ttm,
            forward=forward,
            strike=strike,
            vol=volatility,
            discfactor=discount,
        )
        chain_ts.at[idx, SliceColumn.THETA.value] = bsm.compute_bsm_vanilla_theta(
            discount_rate=discount_rate,
            **common,
        )
        chain_ts.at[idx, SliceColumn.GAMMA.value] = bsm.compute_bsm_vanilla_gamma(
            ttm=ttm,
            forward=forward,
            strike=strike,
            vol=volatility,
        )


def _contract_id(ticker: str, expiry: pd.Timestamp, option_type: str, strike: float) -> str:
    return f'{ticker}-{expiry:%Y%m%d}-{option_type}-{strike:g}'


def map_thetadata_eod_options_data(
    option_source: pd.DataFrame,
    spot_source: pd.DataFrame,
    *,
    ticker: str,
    rate_source: pd.DataFrame | None = None,
    liquidity_threshold: float = 1.0,
    contract_size: float = 100.0,
    expiry_time: time = THETADATA_EXPIRY_TIME,
    expiry_timezone: str = THETADATA_TIMEZONE,
) -> dict[str, Any]:
    """Map ThetaData EOD equity-option reports to ``OptionsDataDFs`` inputs.

    ``created`` is the source report timestamp and is normalized to UTC. Spot
    observations are joined only when their own report timestamp is no later
    than the option report, preserving the point-in-time boundary. Expiration
    dates are interpreted as 16:00 New York time by default, suitable for US
    equity and ETF options but not index products with special settlement.

    Parameters
    ----------
    option_source : pandas.DataFrame
        ThetaData ``option_history_eod`` output using Pandas frames.
    spot_source : pandas.DataFrame
        ThetaData ``stock_history_eod`` output using Pandas frames.
    ticker : str
        US equity or ETF option root.
    rate_source : pandas.DataFrame, optional
        ThetaData interest-rate EOD output with ``created`` and percentage
        ``rate`` columns. The latest report available on or before each option
        report anchors its flat continuously compounded discount factor.
    liquidity_threshold : float, default 1.0
        Maximum relative bid/ask spread ``(ask - bid) / mid``.
    contract_size : float, default 100.0
        Units of underlying represented by one contract.
    expiry_time : datetime.time, default 16:00
        Contractual expiry clock time in ``expiry_timezone``.
    expiry_timezone : str, default ``'America/New_York'``
        Timezone used to interpret ThetaData's date-only expiration field.

    Returns
    -------
    dict
        ``chain_ts``, ``spot_data``, and ``ticker`` accepted by
        :class:`option_chain_analytics.OptionsDataDFs`.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError('ticker must not be empty')
    if liquidity_threshold <= 0.0:
        raise ValueError('liquidity_threshold must be positive')
    if contract_size <= 0.0:
        raise ValueError('contract_size must be positive')
    if not isinstance(option_source, pd.DataFrame) or not isinstance(spot_source, pd.DataFrame):
        raise TypeError('ThetaData sources must be Pandas DataFrames')
    if rate_source is not None and not isinstance(rate_source, pd.DataFrame):
        raise TypeError('ThetaData rate source must be a Pandas DataFrame or None')

    missing = _OPTION_COLUMNS.difference(option_source.columns)
    if missing:
        raise ValueError(f'missing ThetaData option EOD columns: {sorted(missing)}')
    spot_data = _normalize_spot_data(spot_source)
    rate_data = _normalize_rate_data(rate_source)

    source = option_source.loc[:, sorted(_OPTION_COLUMNS)].copy()
    symbols = source['symbol'].dropna().astype(str).str.upper().unique()
    if len(symbols) > 0 and (len(symbols) != 1 or symbols[0] != ticker):
        raise ValueError(f'ThetaData option rows do not match ticker={ticker!r}: {symbols.tolist()}')

    numeric_columns = ['strike', 'volume', 'bid_size', 'bid', 'ask_size', 'ask']
    source[numeric_columns] = source[numeric_columns].apply(pd.to_numeric, errors='coerce')
    source['created'] = pd.to_datetime(source['created'], utc=True, errors='raise')
    expiry_dates = pd.to_datetime(source['expiration'], errors='raise').dt.normalize()
    expiry_offset = pd.Timedelta(
        hours=expiry_time.hour,
        minutes=expiry_time.minute,
        seconds=expiry_time.second,
    )
    source['expiry'] = (
        expiry_dates.add(expiry_offset)
        .dt.tz_localize(expiry_timezone, ambiguous='raise', nonexistent='raise')
        .dt.tz_convert('UTC')
    )
    option_types = source['right'].astype(str).str.upper().map(
        {'CALL': 'C', 'PUT': 'P', 'C': 'C', 'P': 'P'}
    )
    if option_types.isna().any():
        invalid = sorted(source.loc[option_types.isna(), 'right'].astype(str).unique())
        raise ValueError(f'unsupported ThetaData option rights: {invalid}')
    source['option_type'] = option_types

    source['mid'] = 0.5 * (source['bid'] + source['ask'])
    source['relative_spread'] = (source['ask'] - source['bid']) / source['mid']
    valid = (
        source['strike'].gt(0.0)
        & source['bid'].ge(0.0)
        & source['ask'].gt(0.0)
        & source['bid'].le(source['ask'])
        & source['relative_spread'].lt(liquidity_threshold)
        & source['expiry'].gt(source['created'])
    )
    source = source.loc[valid].reset_index(drop=True)

    chain_ts = pd.DataFrame(index=source.index)
    chain_ts[SliceColumn.EXCHANGE_TIME.value] = source['created']
    chain_ts[SliceColumn.UNDERLYING_INDEX.value] = ticker
    chain_ts[SliceColumn.FORWARD_PRICE.value] = np.nan
    chain_ts[SliceColumn.SPOT_PRICE.value] = _map_spot_without_look_ahead(
        source['created'],
        spot_data,
    )
    chain_ts[SliceColumn.USD_MULTIPLIER.value] = 1.0
    chain_ts[SliceColumn.MARK_PRICE.value] = source['mid']
    chain_ts[SliceColumn.BID_PRICE.value] = source['bid']
    chain_ts[SliceColumn.ASK_PRICE.value] = source['ask']
    chain_ts[SliceColumn.BID_SIZE.value] = source['bid_size']
    chain_ts[SliceColumn.ASK_SIZE.value] = source['ask_size']
    chain_ts[SliceColumn.MARK_IV.value] = np.nan
    chain_ts[SliceColumn.BID_IV.value] = np.nan
    chain_ts[SliceColumn.ASK_IV.value] = np.nan
    chain_ts[SliceColumn.DELTA.value] = np.nan
    chain_ts[SliceColumn.VEGA.value] = np.nan
    chain_ts[SliceColumn.THETA.value] = np.nan
    chain_ts[SliceColumn.GAMMA.value] = np.nan
    chain_ts[SliceColumn.OPEN_INTEREST.value] = np.nan
    chain_ts[SliceColumn.VOLUME.value] = source['volume']
    chain_ts[SliceColumn.MATURITY_ID.value] = source['expiry'].dt.strftime('%d%b%Y')
    chain_ts[SliceColumn.STRIKE.value] = source['strike']
    chain_ts[SliceColumn.OPTION_TYPE.value] = source['option_type']
    chain_ts[SliceColumn.EXPIRY.value] = source['expiry']
    chain_ts[SliceColumn.TTM.value] = (
        source['expiry'] - source['created']
    ).dt.total_seconds() / SECONDS_PER_YEAR
    chain_ts[SliceColumn.CONTRACT_SIZE.value] = float(contract_size)
    chain_ts[SliceColumn.DISCOUNT.value] = np.nan
    chain_ts[SliceColumn.CONTRACT.value] = [
        _contract_id(ticker, expiry, option_type, strike)
        for expiry, option_type, strike in zip(
            source['expiry'],
            source['option_type'],
            source['strike'],
        )
    ]

    grouped = chain_ts.groupby(
        [SliceColumn.EXCHANGE_TIME.value, SliceColumn.MATURITY_ID.value],
        observed=True,
        sort=False,
    )
    valid_indices: list[Any] = []
    used_rate_anchor = False
    for indices in grouped.groups.values():
        frame = chain_ts.loc[indices]
        rate_discount = _discount_from_rate_data(
            rates=rate_data,
            report_time=pd.Timestamp(frame[SliceColumn.EXCHANGE_TIME.value].iloc[0]),
            ttm=float(frame[SliceColumn.TTM.value].iloc[0]),
        )
        result = _infer_slice_forward_discount(frame, discount=rate_discount)
        if result is None:
            continue
        forward, discount = result
        chain_ts.loc[indices, SliceColumn.FORWARD_PRICE.value] = forward
        chain_ts.loc[indices, SliceColumn.DISCOUNT.value] = discount
        valid_indices.extend(indices)
        used_rate_anchor = used_rate_anchor or rate_discount is not None
    chain_ts = chain_ts.loc[valid_indices].copy()

    if not chain_ts.empty:
        _infer_iv_columns(chain_ts)
        _compute_mark_greeks(chain_ts)
        chain_ts = chain_ts.sort_values(
            [
                SliceColumn.EXCHANGE_TIME.value,
                SliceColumn.EXPIRY.value,
                SliceColumn.STRIKE.value,
                SliceColumn.OPTION_TYPE.value,
            ]
        )
        chain_ts = chain_ts.drop_duplicates(
            [SliceColumn.EXCHANGE_TIME.value, SliceColumn.CONTRACT.value],
            keep='last',
        )
    chain_ts = chain_ts.reindex(columns=[column.value for column in SliceColumn]).reset_index(drop=True)
    chain_ts.attrs['source'] = 'thetadata_option_eod'
    chain_ts.attrs['expiry_convention'] = f'{expiry_time.isoformat()} {expiry_timezone}'
    chain_ts.attrs['price_convention'] = 'USD per underlying unit'
    chain_ts.attrs['spot_alignment'] = 'latest report at or before option report'
    chain_ts.attrs['discount_convention'] = (
        'flat continuously compounded ThetaData EOD rate; forward inferred from parity'
        if used_rate_anchor
        else 'discount and forward inferred from robust call-put parity'
    )
    return {'chain_ts': chain_ts, 'spot_data': spot_data, 'ticker': ticker}


def _create_thetadata_client() -> ThetaDataClientProtocol:
    try:
        from thetadata import ThetaClient
    except ImportError as exc:
        raise ImportError(
            'ThetaData support requires Python 3.12+ and the optional dependency; '
            'install with `pip install "option-chain-analytics[thetadata]"`.'
        ) from exc
    return ThetaClient(dataframe_type='pandas')


def _is_no_data_error(error: Exception) -> bool:
    return error.__class__.__name__ == 'NoDataFoundError' and error.__class__.__module__.startswith(
        'thetadata'
    )


def _as_date(value: date | str | pd.Timestamp, name: str) -> date:
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be date-like') from exc


def _load_interest_rate_data(
    provider: ThetaDataClientProtocol,
    symbol: str | None,
    start_date: date,
    end_date: date,
) -> pd.DataFrame | None:
    if symbol is None:
        return None
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError('rate_symbol must not be empty')
    method = getattr(provider, 'interest_rate_history_eod', None)
    if method is None:
        return None
    try:
        rates = method(
            symbol=symbol,
            start_date=start_date - timedelta(days=7),
            end_date=end_date,
        )
    except Exception as exc:
        if _is_no_data_error(exc):
            return None
        raise
    if not isinstance(rates, pd.DataFrame):
        raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
    return rates


def load_thetadata_eod_options_data(
    ticker: str,
    value_date: date | str | pd.Timestamp,
    *,
    expirations: Sequence[date | str | pd.Timestamp] | None = None,
    min_expiration: date | str | pd.Timestamp | None = None,
    max_expiration: date | str | pd.Timestamp | None = None,
    liquidity_threshold: float = 1.0,
    contract_size: float = 100.0,
    rate_symbol: str | None = 'SOFR',
    client: ThetaDataClientProtocol | None = None,
) -> dict[str, Any]:
    """Fetch one ThetaData EOD equity-option snapshot and normalize it.

    Authentication is delegated to the official client, which supports
    ``THETADATA_API_KEY`` and its documented credentials-file mechanisms. Pass
    an authorized client to reuse a session or to test without network access.

    Parameters
    ----------
    ticker : str
        US equity or ETF option root.
    value_date : date-like
        EOD report date to fetch.
    expirations : sequence of date-like, optional
        Explicit expirations. When omitted, the provider's expiration listing
        is filtered by ``min_expiration`` and ``max_expiration``.
    min_expiration, max_expiration : date-like, optional
        Inclusive expiration bounds. The minimum defaults to ``value_date``.
    liquidity_threshold : float, default 1.0
        Maximum relative bid/ask spread retained by the mapper.
    contract_size : float, default 100.0
        Units of underlying represented by one contract.
    rate_symbol : str, optional, default ``'SOFR'``
        ThetaData EOD interest-rate symbol used to anchor discount factors.
        Pass ``None`` to estimate both forward and discount from option parity.
    client : ThetaDataClientProtocol, optional
        Authorized official client configured for Pandas frames.

    Returns
    -------
    dict
        ``chain_ts``, ``spot_data``, and ``ticker`` accepted by
        :class:`option_chain_analytics.OptionsDataDFs`.
    """
    ticker = ticker.strip().upper()
    report_date = _as_date(value_date, 'value_date')
    provider = client if client is not None else _create_thetadata_client()

    if expirations is None:
        expiration_frame = provider.option_list_expirations(ticker)
        if not isinstance(expiration_frame, pd.DataFrame):
            raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
        if 'expiration' not in expiration_frame.columns:
            raise ValueError('ThetaData expiration listing is missing the expiration column')
        available = [_as_date(value, 'expiration') for value in expiration_frame['expiration']]
    else:
        available = [_as_date(value, 'expiration') for value in expirations]

    lower = report_date if min_expiration is None else _as_date(min_expiration, 'min_expiration')
    upper = None if max_expiration is None else _as_date(max_expiration, 'max_expiration')
    selected = sorted(
        {
            expiration
            for expiration in available
            if expiration >= lower and (upper is None or expiration <= upper)
        }
    )
    if not selected:
        raise ValueError(f'no ThetaData expirations selected for ticker={ticker!r}')

    option_frames: list[pd.DataFrame] = []
    for expiration in selected:
        try:
            frame = provider.option_history_eod(
                start_date=report_date,
                end_date=report_date,
                symbol=ticker,
                expiration=expiration,
            )
        except Exception as exc:
            if _is_no_data_error(exc):
                continue
            raise
        if not isinstance(frame, pd.DataFrame):
            raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
        if not frame.empty:
            option_frames.append(frame)
    if not option_frames:
        raise ValueError(f'no ThetaData option EOD data for ticker={ticker!r} on {report_date}')

    try:
        spot_source = provider.stock_history_eod(
            symbol=ticker,
            start_date=report_date,
            end_date=report_date,
        )
    except Exception as exc:
        if not _is_no_data_error(exc):
            raise
        spot_source = pd.DataFrame(columns=sorted(_SPOT_COLUMNS))
    if not isinstance(spot_source, pd.DataFrame):
        raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
    rate_source = _load_interest_rate_data(
        provider=provider,
        symbol=rate_symbol,
        start_date=report_date,
        end_date=report_date,
    )

    return map_thetadata_eod_options_data(
        option_source=pd.concat(option_frames, ignore_index=True),
        spot_source=spot_source,
        ticker=ticker,
        rate_source=rate_source,
        liquidity_threshold=liquidity_threshold,
        contract_size=contract_size,
    )


def load_thetadata_eod_options_timeseries(
    ticker: str,
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
    *,
    expirations: Sequence[date | str | pd.Timestamp] | None = None,
    min_dte: int = 0,
    max_dte: int = 60,
    strike_range: int | None = 20,
    liquidity_threshold: float = 1.0,
    contract_size: float = 100.0,
    rate_symbol: str | None = 'SOFR',
    client: ThetaDataClientProtocol | None = None,
) -> dict[str, Any]:
    """Fetch and normalize a point-in-time ThetaData EOD option history.

    Each expiration is requested only over report dates where its calendar DTE
    lies inside ``[min_dte, max_dte]``. Set ``min_dte=0`` when the resulting
    panel will be used to mark positions through their final trading session.

    Parameters
    ----------
    ticker : str
        US equity or ETF option root.
    start_date, end_date : date-like
        Inclusive EOD report-date range.
    expirations : sequence of date-like, optional
        Explicit expirations. By default the provider expiration listing is
        filtered to those intersecting the requested report-date/DTE window.
    min_dte, max_dte : int, default 0 and 60
        Inclusive calendar-day bounds used to limit provider requests.
    strike_range : int, optional, default 20
        Provider strike-range parameter. ``None`` requests all strikes.
    liquidity_threshold : float, default 1.0
        Maximum relative bid/ask spread retained by the mapper.
    contract_size : float, default 100.0
        Units of underlying represented by one contract.
    rate_symbol : str, optional, default ``'SOFR'``
        ThetaData EOD interest-rate symbol used as a flat discount anchor.
        Pass ``None`` to estimate discounts from option parity.
    client : ThetaDataClientProtocol, optional
        Authorized official client configured for Pandas frames.

    Returns
    -------
    dict
        ``chain_ts``, ``spot_data``, and ``ticker`` accepted by
        :class:`option_chain_analytics.OptionsDataDFs`.
    """
    ticker = ticker.strip().upper()
    report_start = _as_date(start_date, 'start_date')
    report_end = _as_date(end_date, 'end_date')
    if not ticker:
        raise ValueError('ticker must not be empty')
    if report_start > report_end:
        raise ValueError('start_date must not be after end_date')
    if min_dte < 0 or max_dte < min_dte:
        raise ValueError('require 0 <= min_dte <= max_dte')
    if strike_range is not None and strike_range < 1:
        raise ValueError('strike_range must be positive or None')

    provider = client if client is not None else _create_thetadata_client()
    if expirations is None:
        expiration_frame = provider.option_list_expirations(ticker)
        if not isinstance(expiration_frame, pd.DataFrame):
            raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
        if 'expiration' not in expiration_frame.columns:
            raise ValueError('ThetaData expiration listing is missing the expiration column')
        available = [_as_date(value, 'expiration') for value in expiration_frame['expiration']]
    else:
        available = [_as_date(value, 'expiration') for value in expirations]

    selected = sorted(
        {
            expiration
            for expiration in available
            if expiration >= report_start + timedelta(days=min_dte)
            and expiration <= report_end + timedelta(days=max_dte)
        }
    )
    if not selected:
        raise ValueError('no expirations intersect the requested report-date and DTE windows')

    option_frames: list[pd.DataFrame] = []
    for expiration in selected:
        request_start = max(report_start, expiration - timedelta(days=max_dte))
        request_end = min(report_end, expiration - timedelta(days=min_dte))
        request_kwargs: dict[str, Any] = {
            'start_date': request_start,
            'end_date': request_end,
            'symbol': ticker,
            'expiration': expiration,
        }
        if strike_range is not None:
            request_kwargs['strike_range'] = strike_range
        try:
            frame = provider.option_history_eod(**request_kwargs)
        except Exception as exc:
            if _is_no_data_error(exc):
                continue
            raise
        if not isinstance(frame, pd.DataFrame):
            raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
        if not frame.empty:
            option_frames.append(frame)
    if not option_frames:
        raise ValueError(f'no ThetaData option EOD data for ticker={ticker!r} in the requested range')

    try:
        spot_source = provider.stock_history_eod(
            symbol=ticker,
            start_date=report_start,
            end_date=report_end,
        )
    except Exception as exc:
        if not _is_no_data_error(exc):
            raise
        spot_source = pd.DataFrame(columns=sorted(_SPOT_COLUMNS))
    if not isinstance(spot_source, pd.DataFrame):
        raise TypeError('ThetaData client must be configured with dataframe_type="pandas"')
    rate_source = _load_interest_rate_data(
        provider=provider,
        symbol=rate_symbol,
        start_date=report_start,
        end_date=report_end,
    )

    return map_thetadata_eod_options_data(
        option_source=pd.concat(option_frames, ignore_index=True),
        spot_source=spot_source,
        ticker=ticker,
        rate_source=rate_source,
        liquidity_threshold=liquidity_threshold,
        contract_size=contract_size,
    )
