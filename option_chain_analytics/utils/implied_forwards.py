import pandas as pd
import numpy as np
from typing import Tuple, Optional


def infer_forward_discount_from_call_put_parity(call0: float, call1: float,
                                                put0: float, put1: float,
                                                strike0: float, strike1: float,
                                                discount: float = None,
                                                discfactor_upper_bound: float = None,
                                                discfactor_lower_bound: float = None
                                                ) -> Tuple[float, float]:
    """
    by put-call parity:
    c_0-p_0 =  discount*forward - discount*strike_0
    c_1-p_1 =  discount*forward - discount*strike_1
    if discount is not passed, it is inferred
    """
    if discount is None:
        discount = - ((call0 - put0) - (call1 - put1)) / (strike0 - strike1)
        # add checks
        if discfactor_upper_bound is not None and discount > discfactor_upper_bound:
            discount = discfactor_upper_bound
        elif discfactor_lower_bound is not None and discount < discfactor_lower_bound:
            discount = discfactor_lower_bound

    forward = 0.5 * (((call0 - put0) + (call1 - put1)) / discount + (strike0 + strike1))
    return forward, discount


def imply_forward_discount_from_mark_prices(call_mark_prices: pd.Series,
                                            put_mark_prices: pd.Series,
                                            discfactor_upper_bound: float = None,
                                            discfactor_lower_bound: float = None,
                                            niters: int = 4
                                            ) -> Optional[Tuple[float, float]]:
    """
    find index where Call-put changes sign
    calls and puts are frames with traded options indexed by strikes with 'ask' and 'bid' columns
    """
    joint_strikes = list(set(call_mark_prices.dropna().index.to_list()) & set(put_mark_prices.dropna().index.to_list()))
    if len(joint_strikes) == 0:
        return None
    atm_strikes = pd.Series(joint_strikes, index=joint_strikes).dropna().sort_index()
    strikes = atm_strikes.to_numpy()
    calls = call_mark_prices.loc[strikes]  # alighn
    puts = put_mark_prices.loc[strikes]  # alighn

    # find where the spread changes sign
    spread = puts - calls
    idx = np.where(np.diff(np.sign(spread)) != 0)[0] + 1  # index where spread goes from negative to positive
    if len(idx) == 0:
        if len(spread) >= 2:
            idx = len(spread)-1
        else:
            return None
    else:
        idx = idx[0]

    discount = None
    for n in np.arange(niters):
        forward, _ = infer_forward_discount_from_call_put_parity(call0=calls.iloc[idx - 1], call1=calls.iloc[idx],
                                                                 put0=puts.iloc[idx - 1], put1=puts.iloc[idx],
                                                                 strike0=strikes[idx - 1], strike1=strikes[idx],
                                                                 discount=discount)

    # fit r
        x = forward - strikes
        y = spread.to_numpy()
        # weight = np.reciprocal(np.maximum(np.square(strikes/forward-1.0), 1e-4))
        # weight = weight / np.nansum(weight)
        discount = - np.reciprocal(np.inner(x, x)) * np.inner(x, y)
        print(f"{n}:  forward={forward}, discount={discount}")

    return forward, discount


def imply_forward_discount_from_bid_ask_prices(calls_bid_ask: pd.DataFrame,
                                               put_bid_ask: pd.DataFrame,
                                               discfactor_upper_bound: float = None,
                                               discfactor_lower_bound: float = None,
                                               niters: int = 4
                                               ) -> Optional[Tuple[float, float]]:
    """
    find index where Call-put changes sign
    calls and puts are frames with traded options indexed by strikes with 'ask' and 'bid' columns
    """
    # remove bid / ask with nans
    calls = calls_bid_ask.replace({0.0: np.nan}).dropna(axis=0, how='any')
    puts = put_bid_ask.replace({0.0: np.nan}).dropna(axis=0, how='any')

    joint_strikes = list(set(calls.index.to_list()) & set(puts.index.to_list()))
    if len(joint_strikes) == 0:
        return None
    atm_strikes = pd.Series(joint_strikes, index=joint_strikes).dropna().sort_index()
    calls = calls.loc[atm_strikes, :]  # alighn
    puts = puts.loc[atm_strikes, :]  # alighn
    strikes = atm_strikes.to_numpy()
    bid_call, ask_call = calls.iloc[:, 0].to_numpy(), calls.iloc[:, 1].to_numpy()
    bid_put, ask_put = puts.iloc[:, 0].to_numpy(), puts.iloc[:, 1].to_numpy()

    mid_call = 0.5*(ask_call + bid_call)
    mid_put = 0.5*(ask_put + bid_put)

    # find where the spread changes sign
    spread = mid_put - mid_call
    idx = np.where(np.diff(np.sign(spread)) != 0)[0] + 1  # index where spread goes from negative to positive
    if len(idx) == 0:
        if len(spread) >= 2:
            idx = len(spread)-1
        else:
            return None
    else:
        idx = idx[0]

    discount = None
    for n in np.arange(niters):
        forward, _ = infer_forward_discount_from_call_put_parity(call0=mid_call[idx - 1], call1=mid_call[idx],
                                                                 put0=mid_put[idx - 1], put1=mid_put[idx],
                                                                 strike0=strikes[idx - 1], strike1=strikes[idx],
                                                                 discount=discount,
                                                                 discfactor_upper_bound=discfactor_upper_bound,
                                                                 discfactor_lower_bound=discfactor_lower_bound)

    # fit r
        x = forward - strikes
        y = spread
        # weight = np.reciprocal(np.maximum(np.square(strikes/forward-1.0), 1e-4))
        # weight = weight / np.nansum(weight)
        discount = - np.reciprocal(np.inner(x, x)) * np.inner(x, y)
        print(f"{n}:  forward={forward}, discount={discount}")

    return forward, discount
