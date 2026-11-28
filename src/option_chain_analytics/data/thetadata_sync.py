"""Validate ETF NBBOs at a common New York valuation cutoff."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

ZONE = 'America/New_York'
KEY = ['symbol', 'expiration', 'strike', 'right']
GREEK_FIELDS = ('bid', 'ask', 'implied_vol', 'delta', 'vega', 'iv_error', 'underlying_price')
QUOTE_FIELDS = ('bid', 'ask', 'bid_size', 'ask_size', 'bid_exchange', 'ask_exchange',
                'bid_condition', 'ask_condition')


def timestamps(values: pd.Series) -> pd.Series:
    """Parse SDK timestamps, interpreting naive wall clocks in New York."""
    strings = values.astype('string')
    explicit = strings.str.contains(r'(?:Z|[+-]\d{2}:?\d{2})$', na=False)
    result = pd.Series(pd.NaT, index=values.index, dtype='datetime64[ns, UTC]')
    if explicit.any():
        result.loc[explicit] = pd.to_datetime(strings.loc[explicit], utc=True, errors='coerce', format='mixed')
    if (~explicit).any():
        ny = pd.to_datetime(strings.loc[~explicit], errors='coerce', format='mixed')
        result.loc[~explicit] = ny.dt.tz_localize(ZONE, ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
    return result


def schedule(exceptions: pd.DataFrame, start: date, end: date, completed_at: pd.Timestamp) -> pd.DataFrame:
    """Build a completed-session schedule from an exchange exception calendar."""
    if completed_at.tzinfo is None or start > end:
        raise ValueError('Require an ordered date range and a timezone-aware completion time')
    rows = exceptions.copy()
    rows['date'] = pd.to_datetime(rows['date'], errors='raise').dt.strftime('%Y-%m-%d')
    rows['type'] = rows['type'].str.lower()
    supported = {'closed', 'full_close', 'holiday', 'early_close', 'late_open', 'open'}
    if rows['date'].duplicated().any() or not rows['type'].isin(supported).all():
        raise ValueError('Unexpected market-calendar exception')
    lookup = rows.set_index('date').to_dict('index')
    result = []
    for day in pd.bdate_range(start, end).strftime('%Y-%m-%d'):
        event = lookup.get(day, {})
        if event.get('type') in {'closed', 'full_close', 'holiday'}:
            continue
        early = event.get('type') == 'early_close'
        close = pd.Timestamp(f"{day} {event['close'] if early else '16:00:00'}", tz=ZONE)
        if close > completed_at:
            continue
        cutoff = close - pd.Timedelta(minutes=5)
        result.append({'date': day, 'time_of_day': cutoff.strftime('%H:%M:%S'),
                       'market_close': close.tz_convert('UTC'), 'snapshot_timestamp': cutoff.tz_convert('UTC'),
                       'early_close': early})
    return pd.DataFrame(result, columns=['date', 'time_of_day', 'market_close', 'snapshot_timestamp', 'early_close'])


def same_session(stamps: pd.Series, cutoff: pd.Timestamp) -> pd.Series:
    """Return observations in the cutoff's New York session."""
    return stamps.dt.tz_convert(ZONE).dt.date.eq(cutoff.tz_convert(ZONE).date())


def valid_prices(frame: pd.DataFrame, *, minimum_bid: float) -> tuple[pd.Series, pd.Series]:
    bid = pd.to_numeric(frame['bid'], errors='coerce')
    ask = pd.to_numeric(frame['ask'], errors='coerce')
    bad_price = ~np.isfinite(bid) | ~np.isfinite(ask) | bid.lt(minimum_bid) | ask.le(0)
    return bad_price, bid.gt(ask)


def conditions(frame: pd.DataFrame, allowed: tuple[int, ...]) -> pd.Series:
    return ~frame.reindex(columns=['bid_condition', 'ask_condition']).isin(allowed).all(axis=1)


def check_stock(stock: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    """Select the latest valid independent stock quote and expose its timestamp semantics."""
    data = {'stock_mid': np.nan, 'stock_quote_timestamp': pd.NaT, 'stock_valid': False,
            'stock_quote_age_seconds': np.nan, 'stock_sample_lag_seconds': np.nan,
            'stock_timestamp_kind': 'unavailable', 'stock_quality': 'missing_stock'}
    for field in QUOTE_FIELDS:
        data[f'stock_{field}'] = np.nan
    if stock.empty:
        return data
    frame = stock.copy()
    frame = frame.reindex(columns=frame.columns.union(QUOTE_FIELDS, sort=False))
    frame['parsed'] = timestamps(frame['timestamp'])
    invalid_price, crossed = valid_prices(frame, minimum_bid=np.nextafter(0., 1.))
    is_session = same_session(frame['parsed'], cutoff)
    if not (is_session & frame['parsed'].le(cutoff)).any():
        data['stock_quality'] = ('future_stock' if (is_session & frame['parsed'].gt(cutoff)).any()
                                 else 'wrong_stock_session' if frame['parsed'].notna().any()
                                 else 'invalid_stock_timestamp')
        return data
    frame = frame.loc[is_session & frame['parsed'].le(cutoff)]
    selected = frame.loc[frame['parsed'].eq(frame['parsed'].max())]
    if len(selected) != 1 and len(selected[['parsed', *QUOTE_FIELDS]].drop_duplicates()) != 1:
        data['stock_quality'] = 'conflicting_stock_quotes'
        return data
    row = selected.iloc[0]
    age = (cutoff - row['parsed']).total_seconds()
    actual_update = age > 0 and row['parsed'] != row['parsed'].floor('min')
    data.update({f'stock_{key}': row[key] for key in QUOTE_FIELDS})
    status = ('invalid_stock_price' if invalid_price.loc[row.name] else 'crossed_stock'
              if crossed.loc[row.name] else 'valid')
    data.update(stock_quote_timestamp=row['parsed'], stock_quote_timestamp_raw=str(row['timestamp']),
                stock_timestamp_kind='reported_event_time' if actual_update else 'sample_grid',
                stock_sample_lag_seconds=age, stock_quote_age_seconds=age if actual_update else np.nan,
                stock_questionable_condition=bool(conditions(selected.iloc[:1], (0, 50)).iloc[0]),
                stock_duplicate_quote=len(selected) > 1, stock_quality=status)
    if status == 'valid':
        data.update(stock_mid=(float(row['bid']) + float(row['ask'])) * .5, stock_valid=True)
    return data


def backward_stock(stocks: pd.DataFrame, references: pd.Series, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Match observed reference times only against stock samples at or before them."""
    out = pd.DataFrame({'reference_stock_mid': np.nan,
                        'reference_stock_timestamp': pd.Series(pd.NaT, index=references.index,
                                                               dtype='datetime64[ns, UTC]')},
                       index=references.index)
    if stocks.empty or references.empty:
        return out
    stamps = timestamps(stocks['timestamp'])
    bad, crossed = valid_prices(stocks, minimum_bid=np.nextafter(0., 1.))
    mask = same_session(stamps, cutoff) & stamps.le(cutoff) & ~bad & ~crossed
    time = pd.DataFrame({'sample': stamps.loc[mask],
                         'mid': (stocks.loc[mask, 'bid'] + stocks.loc[mask, 'ask']) * .5})
    time = time.sort_values('sample').drop_duplicates()
    time = time.loc[~time['sample'].duplicated(keep=False)]
    valid = same_session(references, cutoff) & references.le(cutoff)
    if time.empty or not valid.any():
        return out
    left = references.loc[valid].rename('reference').to_frame().assign(row=lambda frame: frame.index)
    match = pd.merge_asof(left.sort_values('reference'), time, left_on='reference', right_on='sample',
                          direction='backward').set_index('row')
    out.loc[match.index, 'reference_stock_mid'] = match['mid']
    out.loc[match.index, 'reference_stock_timestamp'] = match['sample']
    return out


def identities(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result['symbol'] = frame['symbol'].astype('string')
    result['expiration'] = pd.to_datetime(frame['expiration'], errors='coerce').dt.normalize()
    result['strike'] = pd.to_numeric(frame['strike'], errors='coerce')
    result['right'] = frame['right'].str.upper().replace({'C': 'CALL', 'P': 'PUT'})
    return result


def attach_greeks(options: pd.DataFrame, greeks: pd.DataFrame, cutoff: pd.Timestamp,
                  stock_samples: pd.DataFrame) -> pd.DataFrame:
    if greeks.empty:
        return options.assign(provider_greeks_matched=False)
    frame = identities(greeks).reset_index(drop=True)
    frame['provider_greeks_timestamp_raw'] = frame['timestamp'].astype('string')
    frame['provider_greeks_timestamp'] = timestamps(frame['timestamp'])
    underlying = frame.get('underlying_timestamp', pd.Series(None, index=frame.index))
    frame['provider_underlying_timestamp_raw'] = underlying.astype('string')
    frame['provider_underlying_timestamp'] = timestamps(underlying)
    stamp = frame['provider_greeks_timestamp']
    frame = frame.loc[same_session(stamp, cutoff) & stamp.le(cutoff)].copy()
    duplicate = frame.duplicated([*KEY, 'provider_greeks_timestamp'], keep=False)
    frame = frame.loc[~duplicate].sort_values('provider_greeks_timestamp').drop_duplicates(KEY, keep='last')
    reference = frame['provider_underlying_timestamp']
    reference_valid = same_session(reference, cutoff) & reference.le(frame['provider_greeks_timestamp'])
    comparison = backward_stock(stock_samples, reference.where(reference_valid), cutoff)
    frame = frame.join(comparison)
    frame.rename(columns={key: f'provider_{key}' for key in GREEK_FIELDS if key in frame}, inplace=True)
    frame['provider_reference_valid'] = reference_valid
    frame['provider_greeks_matched'] = True
    fields = [*KEY, *(key for key in frame if key.startswith(('provider_', 'reference_stock_')))]
    output = options.merge(frame[fields], on=KEY, how='left', validate='many_to_one')
    output['provider_greeks_matched'] = output['provider_greeks_matched'].eq(True)
    output['provider_greeks_timestamp_kind'] = 'sample_grid_1m'
    output['provider_reference_matching'] = 'independent_stock_sample_backward_1s'
    if 'provider_underlying_price' in output:
        output['provider_underlying_minus_cutoff_mid'] = output['provider_underlying_price'] - output['stock_mid']
        output['provider_underlying_minus_reference_mid'] = (
            output['provider_underlying_price'] - output['reference_stock_mid']
        )
    return output


def normalize(ticker: str, cutoff: pd.Timestamp, stock: pd.DataFrame, options: pd.DataFrame,
              greeks: pd.DataFrame, *, max_dte: int = 460, strike_range: int | None = None,
              option_max_age: float | None = None, stock_samples: pd.DataFrame | None = None
              ) -> tuple[pd.DataFrame, dict]:
    """Build a quote panel and a status row while leaving raw input frames untouched."""
    cutoff = cutoff.tz_convert('UTC')
    status = check_stock(stock.reset_index(drop=True), cutoff)
    status.update(ticker=ticker, snapshot_timestamp=cutoff, stock_source='thetadata_stock_at_time_quote:utp_cta',
                  option_source='thetadata_option_at_time_quote:opra', options_available=not options.empty)
    if options.empty:
        return pd.DataFrame(), {**status, 'aligned': False, 'quality': 'missing_options', 'eligible_rows': 0}
    data = identities(options).reset_index(drop=True)
    data['option_quote_timestamp_raw'] = data['timestamp'].astype('string')
    stamp = data['option_quote_timestamp'] = timestamps(data['timestamp'])
    age = data['option_quote_age_seconds'] = (cutoff - stamp).dt.total_seconds()
    data['option_timestamp_kind'] = 'actual_update'
    day = cutoff.tz_convert(ZONE).date()
    data['calendar_dte'] = (data['expiration'] - pd.Timestamp(day)).dt.days
    invalid_price, crossed = valid_prices(data, minimum_bid=0.)
    flags = pd.DataFrame({
        'invalid_timestamp': stamp.isna(), 'wrong_session': stamp.notna() & ~same_session(stamp, cutoff),
        'future_quote': stamp.gt(cutoff), 'invalid_price': invalid_price, 'crossed_market': crossed,
        'duplicate_identity': data.duplicated(KEY, keep=False),
        'invalid_identity': (~data['symbol'].eq(ticker) | ~data['right'].isin(['CALL', 'PUT'])
                             | ~np.isfinite(data['strike']) | data['strike'].le(0)).fillna(True),
        'outside_dte': ~data['calendar_dte'].between(0, max_dte),
    })
    if strike_range is not None and status['stock_valid']:
        strikes = data[['expiration', 'strike']].dropna().drop_duplicates()
        spot_mid = status['stock_mid']
        selected = [block.loc[block.strike.lt(spot_mid)].nlargest(strike_range, 'strike')
                    for _, block in strikes.groupby('expiration')]
        selected += [block.loc[block.strike.gt(spot_mid)].nsmallest(strike_range, 'strike')
                     for _, block in strikes.groupby('expiration')]
        within = pd.concat([strikes.loc[strikes.strike.eq(spot_mid)], *selected], ignore_index=True)
        flags['outside_strike_range'] = ~pd.MultiIndex.from_frame(data[['expiration', 'strike']]).isin(
            pd.MultiIndex.from_frame(within),
        )
    data['option_questionable_condition'] = conditions(data, (0, 50))
    data['option_zero_bid'] = data['bid'].eq(0)
    data['option_quote_older_60s'] = age.gt(60)
    data['option_quote_older_300s'] = age.gt(300)
    data['option_relative_spread'] = (data['ask'] - data['bid']) / ((data['ask'] + data['bid']) * .5)
    if option_max_age is not None:
        flags['option_age_limit'] = age.gt(option_max_age)
    flags = flags.fillna(True)
    data = data.join(flags.add_prefix('flag_'))
    data['eligible'] = ~flags.any(axis=1) & status['stock_valid']
    reasons = np.full(len(flags), '', dtype=object)
    for flag, mask in flags.items():
        reasons[mask.to_numpy()] += f'|{flag}'
    data['failure_reasons'] = pd.Series(reasons, index=flags.index, dtype='string').str.lstrip('|')
    if not status['stock_valid']:
        data['failure_reasons'] = data['failure_reasons'].str.cat(
            pd.Series(status['stock_quality'], index=data.index), sep='|',
        ).str.strip('|')
    for field, value in status.items():
        data[field] = value
    samples = stock if stock_samples is None else stock_samples
    data = attach_greeks(data, greeks, cutoff, samples)
    count = int(data['eligible'].sum())
    return data, {**status, 'aligned': count > 0, 'eligible_rows': count,
                  'quality': 'valid' if count else status['stock_quality'] if not status['stock_valid']
                  else 'no_eligible_options'}
