"""Point-in-time reconstruction of expiry-sliced option chains."""

from typing import Dict, Literal, Optional

import numpy as np
import pandas as pd
import qis
from qis import TimePeriod
from qis.utils.np_ops import np_nonan_weighted_avg

from option_chain_analytics.option_chain import (
    ExpirySlice,
    SliceColumn,
    SlicesChain,
    UnderlyingColumn,
)
from option_chain_analytics.option_data import OptionsDataDFs


def create_chain_at_time(
    options_data: OptionsDataDFs,
    value_time: pd.Timestamp,
    time_selection: Literal['exact', 'previous'] = 'exact',
) -> Optional[SlicesChain]:
    """Reconstruct the option chain available at one observation time.

    Parameters
    ----------
    options_data : OptionsDataDFs
        Provider-normalized option observations.
    value_time : pandas.Timestamp
        Requested observation or schedule time.
    time_selection : {'exact', 'previous'}, default='exact'
        Selection policy. ``previous`` selects the latest observation at or
        before ``value_time`` and never selects a future row.

    Returns
    -------
    SlicesChain or None
        Reconstructed expiry slices, or ``None`` when no permitted observation
        exists. The chain's ``value_time`` is the actual selected feed time.
    """
    options_df = options_data.get_time_slice(
        timestamp=value_time,
        time_selection=time_selection,
    )
    if options_df.empty:
        return None

    selected_value_time = pd.Timestamp(
        options_df[SliceColumn.EXCHANGE_TIME.value].iloc[0]
    )
    expiry_slices = {}
    underlying_data = {}
    for maturity_id, maturity_df in options_df.groupby(SliceColumn.MATURITY_ID.value):
        open_interest = maturity_df[SliceColumn.OPEN_INTEREST]
        if open_interest.notna().any():
            forward = np_nonan_weighted_avg(
                a=maturity_df[SliceColumn.FORWARD_PRICE.value],
                weights=open_interest,
            )
        else:
            forward = np.nanmean(maturity_df[SliceColumn.FORWARD_PRICE.value])
        if np.isnan(forward):
            continue

        expiry_id = str(maturity_id)
        expiry_data = pd.Series(
            {
                UnderlyingColumn.EXPIRY_ID: expiry_id,
                UnderlyingColumn.VALUE_TIME: selected_value_time,
                UnderlyingColumn.EXPIRY: maturity_df[SliceColumn.EXPIRY].iloc[0],
                UnderlyingColumn.SPOT_PRICE: forward,
                UnderlyingColumn.UNDERLYING_INDEX: expiry_id,
                UnderlyingColumn.FORWARD_PRICE: forward,
                UnderlyingColumn.IR_RATE: 0.0,
                UnderlyingColumn.TTM: maturity_df[SliceColumn.TTM].iloc[0],
            }
        )
        expiry_slices[expiry_id] = ExpirySlice(
            options_df=maturity_df,
            undelying_data=expiry_data,
        )
        underlying_data[expiry_id] = expiry_data

    underlying_df = pd.DataFrame.from_dict(underlying_data, orient='index')
    return SlicesChain(
        options_df=options_df,
        undelying_df=underlying_df,
        expiry_slices=expiry_slices,
        value_time=selected_value_time,
    )


def create_chain_timeseries(
    options_data: OptionsDataDFs,
    dates_schedule: Optional[pd.DatetimeIndex] = None,
    time_period: Optional[TimePeriod] = None,
    freq: str = 'W-FRI',
    hour_offset: int = 8,
    time_selection: Literal['exact', 'previous'] = 'previous',
) -> Dict[pd.Timestamp, SlicesChain]:
    """Reconstruct chains along an explicit or generated point-in-time schedule.

    Parameters
    ----------
    options_data : OptionsDataDFs
        Provider-normalized option observations.
    dates_schedule : pandas.DatetimeIndex, optional
        Explicit requested timestamps.
    time_period : qis.TimePeriod, optional
        Period used to generate a schedule when ``dates_schedule`` is omitted.
    freq : str, default='W-FRI'
        Schedule frequency passed to :func:`qis.generate_dates_schedule`.
    hour_offset : int, default=8
        Schedule hour in UTC.
    time_selection : {'exact', 'previous'}, default='previous'
        Point-in-time selection policy for each requested timestamp.

    Returns
    -------
    dict[pandas.Timestamp, SlicesChain]
        Available reconstructed chains keyed by requested schedule timestamp.

    Raises
    ------
    ValueError
        If neither ``dates_schedule`` nor ``time_period`` is supplied.
    """
    if dates_schedule is None:
        if time_period is None:
            raise ValueError('time_period is required when dates_schedule is omitted')
        dates_schedule = qis.generate_dates_schedule(
            time_period=time_period,
            freq=freq,
            hour_offset=hour_offset,
        )

    chains = {}
    for timestamp in dates_schedule:
        chain = create_chain_at_time(
            options_data=options_data,
            value_time=timestamp,
            time_selection=time_selection,
        )
        if chain is not None:
            chains[timestamp] = chain
    return chains
