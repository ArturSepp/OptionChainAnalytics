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
        if discount > discfactor_upper_bound:
            discount = discfactor_upper_bound
        elif discount < discfactor_lower_bound:
            discount = discfactor_lower_bound

    forward = 0.5 * (((call0 - put0) + (call1 - put1)) / discount + (strike0 + strike1))
    return forward, discount


def imply_forward_discount(calls: pd.DataFrame,
                           puts: pd.DataFrame,
                           discfactor_upper_bound: float = None,
                           discfactor_lower_bound: float = None
                           ) -> Optional[Tuple[float, float]]:
    """
    find index where Call-put changes sign
    calls and puts are frames with traded options indexed by strikes with 'ask' and 'bid' columns
    """
    # remove bid / ask with nans
    calls = calls.dropna(subset=['bid', 'ask'], how='all')
    puts = puts.dropna(subset=['bid', 'ask'], how='all')

    joint_strikes = list(set(calls.index.to_list()) & set(puts.index.to_list()))

    if len(joint_strikes) == 0:
        return None
    atm_strikes = pd.Series(joint_strikes, index=joint_strikes).dropna().sort_index()
    calls = calls.loc[atm_strikes, :]  # alighn
    puts = puts.loc[atm_strikes, :]  # alighn
    strikes = atm_strikes.to_numpy()
    ask_call, bid_call = calls['ask'].to_numpy(), calls['bid'].to_numpy()
    ask_put, bid_put = puts['ask'].to_numpy(), puts['bid'].to_numpy()

    # fill when both nans with last
    is_ask_call = np.isnan(ask_call) == False
    is_bid_call = np.isnan(bid_call) == False
    calls_not_nans = np.logical_and(is_ask_call, is_bid_call)
    mid_call = 0.5*(ask_call + bid_call)
    mid_call = np.where(calls_not_nans, mid_call, np.where(is_ask_call, ask_call, bid_call))

    is_ask_put = np.isnan(ask_put) == False
    is_bid_put = np.isnan(bid_put) == False
    puts_not_nans = np.logical_and(is_ask_put, is_bid_put)
    mid_put = 0.5*(ask_put + bid_put)
    mid_put = np.where(puts_not_nans, mid_put, np.where(is_ask_put, ask_put, bid_put))

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
    forward, discount = infer_forward_discount_from_call_put_parity(call0=mid_call[idx - 1], call1=mid_call[idx],
                                                                    put0=mid_put[idx - 1], put1=mid_put[idx],
                                                                    strike0=strikes[idx - 1], strike1=strikes[idx],
                                                                    discfactor_upper_bound=discfactor_upper_bound,
                                                                    discfactor_lower_bound=discfactor_lower_bound)

    return forward, discount
