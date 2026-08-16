"""
fit spline to prices
example usage in volatility_book/ch_implied_vol/fit_price_spline
"""
from enum import Enum
from typing import Optional, Tuple

import cvxpy as cvx
import numpy as np
import pandas as pd
import qis as qis
from scipy.interpolate import BSpline, make_interp_spline

from option_chain_analytics.fitters.utils import SliceFitOutputs, imply_bid_ask_mark_vols
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.utils.implied_forwards import imply_forward_discount_from_bid_ask_prices
from option_chain_analytics.utils.numerics import set_matrix_d1_d2, set_matrix_diff1_diff2, set_matrix_g


class WeightType(Enum):
    IDENTITY = 1
    TIME_VALUE = 2
    BID_ASK_SPREAD = 3
    ABS_MONEYNESS = 4


def fit_slice_mark_prices_implied_vols_with_qp_solver(slice_df: pd.DataFrame,
                                                      weight_type: WeightType = WeightType.BID_ASK_SPREAD,
                                                      eps: float = 0.0001,
                                                      bid_ask_contraint_band: float = 0.99,  # will also be multpilied by weights
                                                      verbose: bool = False,
                                                      is_apply_bspline: bool = False
                                                      ) -> Tuple[SliceFitOutputs, Optional[BSpline], Optional[BSpline]]:
    """
    slice_df must be indexed by strikes
    fit mark prices and compute implied vols
    """
    calls = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'C', :]
    puts = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'P', :]
    out = imply_forward_discount_from_bid_ask_prices(calls_bid_ask=calls[[SliceColumn.BID_PRICE, SliceColumn.ASK_PRICE]],
                                                     put_bid_ask=puts[[SliceColumn.BID_PRICE, SliceColumn.ASK_PRICE]])

    if out is not None:
        forward, discfactor = out
        print(f"implied forward={forward}, discfactor2={discfactor}")
    else:
        forward = float(np.nanmean(slice_df[SliceColumn.SPOT_PRICE.value]))
        discfactor = 1.0
        print(f"failed to imply forward: using spot proce = {forward} and discfactor={discfactor}")

    mark_prices, call_spline, put_spline = infer_call_put_prices_with_qp_solver(slice_df=slice_df,
                                                                                forward=forward,
                                                                                discfactor=discfactor,
                                                                                weight_type=weight_type,
                                                                                eps=eps,
                                                                                is_reindex_to_slice_strikes=True,
                                                                                bid_ask_contraint_band=bid_ask_contraint_band,
                                                                                verbose=verbose,
                                                                                is_apply_bspline=is_apply_bspline)

    call_mark_prices = mark_prices.iloc[:, 0]
    put_mark_prices = mark_prices.iloc[:, 1]

    ttm = slice_df[SliceColumn.TTM].iloc[0]
    calls_bid = calls[SliceColumn.BID_PRICE].to_numpy(float)  # do not change the raw data
    calls_ask = calls[SliceColumn.ASK_PRICE].to_numpy(float)
    puts_bid = puts[SliceColumn.BID_PRICE].to_numpy(float)
    puts_ask = puts[SliceColumn.ASK_PRICE].to_numpy(float)
    call_strikes = calls[SliceColumn.STRIKE].to_numpy(float)
    put_strikes = puts[SliceColumn.STRIKE].to_numpy(float)

    calls_bid_iv, calls_ask_iv, calls_mark_iv = imply_bid_ask_mark_vols(strikes=call_strikes,
                                                                        bid_prices=calls_bid,
                                                                        ask_prices=calls_ask,
                                                                        mark_prices=call_mark_prices.to_numpy(),
                                                                        ttm=ttm,
                                                                        forward=forward,
                                                                        discfactor=discfactor,
                                                                        optiontype='C')

    puts_bid_iv, puts_ask_iv, puts_mark_iv = imply_bid_ask_mark_vols(strikes=put_strikes,
                                                                     bid_prices=puts_bid,
                                                                     ask_prices=puts_ask,
                                                                     mark_prices=put_mark_prices.to_numpy(),
                                                                     ttm=ttm,
                                                                     forward=forward,
                                                                     discfactor=discfactor,
                                                                     optiontype='P')
    slice_fit_outputs = SliceFitOutputs(forward=forward,
                                        discfactor=discfactor,
                                        call_mark_prices=call_mark_prices,
                                        put_mark_prices=put_mark_prices,
                                        calls_bid_iv=calls_bid_iv,
                                        calls_ask_iv=calls_ask_iv,
                                        calls_mark_iv=calls_mark_iv,
                                        puts_bid_iv=puts_bid_iv,
                                        puts_ask_iv=puts_ask_iv,
                                        puts_mark_iv=puts_mark_iv)
    return slice_fit_outputs, call_spline, put_spline


def infer_call_put_prices_with_qp_solver(slice_df: pd.DataFrame,
                                         forward: float,
                                         discfactor: float,
                                         weight_type: WeightType = WeightType.BID_ASK_SPREAD,
                                         eps: float = 0.0001,
                                         bid_ask_contraint_band: float = 0.99,  # deflate / inflate
                                         verbose: bool = True,
                                         is_reindex_to_slice_strikes: bool = False,
                                         total_num_of_iterations: int = 5,
                                         is_apply_bspline: bool = False
                                         ) -> Tuple[pd.DataFrame, Optional[BSpline], Optional[BSpline]]:
    """
    given slices infer call and put marks
    """
    calls_slice = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'C', :]
    puts_slice = slice_df.loc[slice_df[SliceColumn.OPTION_TYPE.value] == 'P', :]

    for n in np.arange(total_num_of_iterations):
        if is_apply_bspline:
            call_marks, put_marks, call_spline, put_spline = infer_mark_call_put_price_with_qp_solver_bspline(
                call_bid_ask_prices=calls_slice[[SliceColumn.BID_PRICE, SliceColumn.ASK_PRICE]],
                put_bid_ask_prices=puts_slice[[SliceColumn.BID_PRICE, SliceColumn.ASK_PRICE]],
                forward_price=forward,
                discfactor=discfactor,
                eps=eps,
                bid_ask_contraint_band=bid_ask_contraint_band,
                weight_type=weight_type,
                verbose=verbose)
        else:
            call_marks, put_marks = infer_mark_call_put_price_with_qp_solver(
                call_bid_ask_prices=calls_slice[[SliceColumn.BID_PRICE, SliceColumn.ASK_PRICE]],
                put_bid_ask_prices=puts_slice[[SliceColumn.BID_PRICE, SliceColumn.ASK_PRICE]],
                forward_price=forward,
                discfactor=discfactor,
                eps=eps,
                bid_ask_contraint_band=bid_ask_contraint_band,
                weight_type=weight_type,
                verbose=verbose)
            call_spline, put_spline = None, None
        if call_marks is not None:
            print(f"solved iteration={n+1} with eps={eps}, bid_ask_contraint_band={bid_ask_contraint_band}")
            break
        else:
            print(f"unsolved iteration={n+1} with eps={eps}, bid_ask_contraint_band={bid_ask_contraint_band}"
                  f" reducing eps by 0.1 and increasing bid_ask_contraint_band by 5.0 ")
            eps *= 0.1
            bid_ask_contraint_band *=2.0

    mark_prices = pd.concat([call_marks, put_marks], axis=1).sort_index()
    if is_reindex_to_slice_strikes:  # reindex to given strikes
        slice_strikes = pd.Index(slice_df[SliceColumn.STRIKE.value].unique())
        mark_prices = mark_prices.reindex(index=slice_strikes).sort_index()

    return mark_prices, call_spline, put_spline


def compute_eror_weights(weight_type: WeightType,
                         strikes: np.ndarray,
                         bid_price: np.ndarray,
                         ask_price: np.ndarray,
                         forward_price: float,
                         is_calls: bool,
                         is_norm: bool = True
                         ) -> np.ndarray:
    """
    set error weights for QP problem
    """
    # set error weights
    if weight_type == WeightType.IDENTITY:
        w = np.identity(strikes.shape[0])

    elif weight_type == WeightType.TIME_VALUE:
        mid_price = 0.5 * (bid_price + ask_price)
        # floor time_value to 1e-8
        if is_calls:
            time_value = np.maximum(mid_price - np.maximum(forward_price - strikes, 0.0), 1e-16)
        else:
            time_value = np.maximum(mid_price - np.maximum(strikes - forward_price, 0.0), 1e-16)

        time_value = time_value / forward_price # / np.nansum(time_value)
        abs_m = np.reciprocal(np.maximum(np.abs(strikes - forward_price), 1e-8))
        w = np.diag(time_value)

    elif weight_type == WeightType.ABS_MONEYNESS:
        abs_m = np.maximum(np.abs(strikes - forward_price), 1e-8)
        w = np.diag(np.reciprocal(abs_m))

    elif weight_type == WeightType.BID_ASK_SPREAD:
        spread = (ask_price - bid_price)
        w = np.reciprocal(spread)
        if is_norm:
            w = w / np.nansum(w)
        w = np.diag(w)
    else:
        raise NotImplementedError(f"weight_type={weight_type}")
    return w


def get_aligned_bid_ask_prices(bid_ask_prices: pd.DataFrame,
                               norm_factor: float = 1.0
                               ) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    align bid and ask prices and assigne the weight
    validity: 0: both are nans, 1: one is nan, 2: both are good
    """
    joint_prices = (1.0/norm_factor) * bid_ask_prices.sort_index()
    bid_prices, ask_prices = joint_prices.iloc[:, 0], joint_prices.iloc[:, 1]
    mid_prices = 0.5*(bid_prices + ask_prices)
    quote_validity = pd.Series(np.where(pd.isna(mid_prices) == False, 1, 0), index=mid_prices.index)
    bid_ask_spread = 0.5*(ask_prices-bid_prices)
    return mid_prices, quote_validity, bid_ask_spread, bid_prices, ask_prices


def infer_mark_call_put_price_with_qp_solver(call_bid_ask_prices: pd.DataFrame,
                                             put_bid_ask_prices: pd.DataFrame,
                                             forward_price: float,
                                             discfactor: float,
                                             eps: float = 1e-8,
                                             weight_type: WeightType = WeightType.BID_ASK_SPREAD,
                                             verbose: bool = True,
                                             is_add_bid_ask_constraint: bool = True,
                                             bid_ask_contraint_band: float = 0.99  # deflate / inflate
                                             ) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
    """
    solve qp problem to infer valid mark prices
    """
    norm_factor = forward_price
    # reindex at joint strikes
    joint_strikes = list(set(call_bid_ask_prices.index.to_list()) & set(put_bid_ask_prices.index.to_list()))
    call_bid_ask_prices = call_bid_ask_prices.reindex(index=joint_strikes).sort_index()
    put_bid_ask_prices = put_bid_ask_prices.reindex(index=joint_strikes).sort_index()
    joint_strikes = call_bid_ask_prices.index.to_numpy()
    joint_strikes_norm = joint_strikes / norm_factor

    # set mids and validity
    call_mid_price, call_validity, call_bid_ask_spread, call_bid_prices, call_ask_prices \
        = get_aligned_bid_ask_prices(bid_ask_prices=call_bid_ask_prices, norm_factor=norm_factor)
    put_mid_price, put_validity, put_bid_ask_spread, put_bid_prices, put_ask_prices \
        = get_aligned_bid_ask_prices(bid_ask_prices=put_bid_ask_prices, norm_factor=norm_factor)

    # for solver we need to fill nanns
    call_mid_price = call_mid_price.fillna(0.0).to_numpy()
    put_mid_price = put_mid_price.fillna(0.0).to_numpy()
    # these are used as trackers for weight
    is_call_available = call_validity.to_numpy(float)
    is_put_available = put_validity.to_numpy(float)
    is_call_put_available = is_call_available*is_put_available

    # set error weights
    weight_calls = compute_eror_weights(weight_type=weight_type, strikes=joint_strikes_norm,
                                        bid_price=call_bid_prices.to_numpy(),
                                        ask_price=call_ask_prices.to_numpy(),
                                        forward_price=forward_price,
                                        is_calls=True)

    weight_puts = compute_eror_weights(weight_type=weight_type, strikes=joint_strikes_norm,
                                       bid_price=put_bid_prices.to_numpy(),
                                       ask_price=put_ask_prices.to_numpy(),
                                       forward_price=forward_price,
                                       is_calls=False)
    # multiply by availability
    weight_calls = np.diag(weight_calls)
    weight_puts = np.diag(weight_puts)
    weights_call_put = np.diag(np.concatenate((weight_calls*is_call_available, weight_puts*is_put_available)))
    mid_price = np.concatenate((call_mid_price, put_mid_price))

    # set optimisation problem
    n = len(joint_strikes_norm)
    n2 = 2*n
    z = cvx.Variable(n2, nonneg=True)
    G, D2 = set_matrix_g(x=joint_strikes_norm)
    Q = np.transpose(weights_call_put) @ weights_call_put
    q = - Q @ mid_price

    h1 = -eps*np.ones(n)
    h2 = -eps*np.ones(n)
    h1[0] = discfactor - eps
    h2[-1] = discfactor - eps

    constraints = [G @ z[:n] <= h1]
    constraints = constraints + [G @ z[n:] <= h2]
    # constraints = constraints + [D2 @ z[:n] >= 0.0]
    # constraints = constraints + [D2 @ z[n:] >= 0.0]

    # put call parity
    call_put_rhs = discfactor * (forward_price / norm_factor - joint_strikes_norm)
    bid_ask_spreads = 0.5 * (call_bid_ask_spread.to_numpy() + put_bid_ask_spread.to_numpy())
    call_put_parity_constraints = []
    for idx, is_valid in enumerate(is_call_put_available):
        if is_valid > 0.0:  # put index is shifted by n
            call_put_parity_constraints += [-bid_ask_spreads[idx] <= z[idx] - z[n + idx] - call_put_rhs[idx]]
            call_put_parity_constraints += [bid_ask_spreads[idx] >= z[idx] - z[n + idx] - call_put_rhs[idx]]
    constraints = constraints + call_put_parity_constraints

    if is_add_bid_ask_constraint:
        call_constraints = []
        call_bids = np.maximum((1.0-bid_ask_contraint_band)*call_bid_prices.to_numpy(), 0.0)
        call_asks = (1.0 + bid_ask_contraint_band) * call_ask_prices.to_numpy()
        for idx, (is_call_available_, call_bid, call_ask) in enumerate(zip(is_call_available, call_bids, call_asks)):
            if is_call_available_ > 0:
                call_constraints += [z[idx] >= call_bid]
                call_constraints += [z[idx] <= call_ask]

        put_constraints = []
        put_bids = np.maximum((1.0-bid_ask_contraint_band)*put_bid_prices.to_numpy(), 0.0)
        put_asks = (1.0 + bid_ask_contraint_band) * put_ask_prices.to_numpy()
        for idx, (is_put_available_, put_bid, put_ask) in enumerate(zip(is_put_available, put_bids, put_asks)):
            if is_put_available_ > 0:  # puts are shifted by n
                put_constraints += [z[n+idx] >= put_bid]
                put_constraints += [z[n+idx] <= put_ask]

        constraints = constraints + call_constraints + put_constraints

    dk = np.concatenate((np.array([0.0]), np.reciprocal(joint_strikes_norm[1:] - joint_strikes_norm[:-1])))
    p_sline_conv = G @ z[:n] + G @ z[n:]
    convexity_objective = cvx.norm(p_sline_conv*dk, 2) / n2
    # total objective_fun
    # objective_fun = 1.0e-3*(1.0/np.square(forward_price))*(0.5*cvx.quad_form(z, Q) + q @ z) # + convexity_objective
    objective_fun = (1.0/n2)*(0.5*cvx.quad_form(z, Q) + q @ z) + 1e8*convexity_objective

    objective = cvx.Minimize(objective_fun)
    problem = cvx.Problem(objective, constraints)
    try:
        kwargs = dict(max_iters=20000, feastol=1e-12, abstol=1e-12, reltol=1e-16)
        # problem.solve(solver=cvx.ECOS, verbose=verbose, **kwargs)
        # problem.solve(solver=cvx.ECOS_BB, verbose=verbose, **kwargs)
        problem.solve(solver=cvx.CLARABEL, verbose=verbose)
        #problem.solve(verbose=verbose)
        option_marks = z.value
    except cvx.error.SolverError:
        option_marks = None
    if option_marks is not None:
        print(f"puts: {np.logical_and(option_marks[n:]>=put_bid_prices.to_numpy(), option_marks[n:]<=put_ask_prices.to_numpy())} ")
        call_marks = pd.Series(np.maximum(norm_factor*option_marks[:n], 1e-16), index=joint_strikes, name='calls')
        put_marks = pd.Series(np.maximum(norm_factor*option_marks[n:], 1e-16), index=joint_strikes, name='puts')
    else:
        print(f"problem is not solved, try to decrease smootheness eps={eps}")
        call_marks, put_marks = None, None
    return call_marks, put_marks


# @njit
def bspline_interpolation(x: np.ndarray, b_spline: BSpline) -> np.ndarray:
    """
    given input array x and b_spline compute spline interpolation
    """
    y_spline = np.zeros_like(x)
    for idx, x_ in enumerate(x):
        y_spline[idx] = b_spline(x_, extrapolate=False)
    return y_spline


def infer_mark_call_put_price_with_qp_solver_bspline(call_bid_ask_prices: pd.DataFrame,
                                                     put_bid_ask_prices: pd.DataFrame,
                                                     forward_price: float,
                                                     discfactor: float,
                                                     eps: float = 1e-8,
                                                     weight_type: WeightType = WeightType.BID_ASK_SPREAD,
                                                     verbose: bool = True,
                                                     is_add_bid_ask_constraint: bool = True,
                                                     bid_ask_contraint_band: float = 0.99,  # deflate / inflate
                                                     degree: int = 3
                                                     ) -> Tuple[Optional[pd.Series], Optional[pd.Series], BSpline, BSpline]:
    """
    solve qp problem to infer valid mark prices
    """
    norm_factor = forward_price
    # reindex at joint strikes
    joint_strikes = list(set(call_bid_ask_prices.index.to_list()) & set(put_bid_ask_prices.index.to_list()))
    call_bid_ask_prices = call_bid_ask_prices.reindex(index=joint_strikes).sort_index()
    put_bid_ask_prices = put_bid_ask_prices.reindex(index=joint_strikes).sort_index()
    joint_strikes = call_bid_ask_prices.index.to_numpy()
    joint_strikes_norm = joint_strikes / norm_factor

    # set mids and validity
    call_mid_price, call_validity, call_bid_ask_spread, call_bid_prices, call_ask_prices \
        = get_aligned_bid_ask_prices(bid_ask_prices=call_bid_ask_prices, norm_factor=norm_factor)
    put_mid_price, put_validity, put_bid_ask_spread, put_bid_prices, put_ask_prices \
        = get_aligned_bid_ask_prices(bid_ask_prices=put_bid_ask_prices, norm_factor=norm_factor)

    # for solver we need to fill nanns
    call_mid_price = call_mid_price.fillna(0.0).to_numpy()
    put_mid_price = put_mid_price.fillna(0.0).to_numpy()
    # these are used as trackers for weight
    is_call_available = call_validity.to_numpy(float)
    is_put_available = put_validity.to_numpy(float)
    is_call_put_available = is_call_available*is_put_available

    # set error weights
    weight_calls = compute_eror_weights(weight_type=weight_type,
                                        strikes=joint_strikes_norm,
                                        bid_price=call_bid_prices.to_numpy(),
                                        ask_price=call_ask_prices.to_numpy(),
                                        forward_price=forward_price,
                                        is_calls=True)

    weight_puts = compute_eror_weights(weight_type=weight_type,
                                       strikes=joint_strikes_norm,
                                       bid_price=put_bid_prices.to_numpy(),
                                       ask_price=put_ask_prices.to_numpy(),
                                       forward_price=forward_price,
                                       is_calls=False)
    # multiply by availability
    #weight_calls = np.diag(weight_calls)
    #weight_puts = np.diag(weight_puts)
    # weights_call_put = np.diag(np.concatenate((weight_calls*is_call_available, weight_puts*is_put_available)))

    # Compute the (coefficients of) interpolating B-spline
    bspl = make_interp_spline(x=joint_strikes_norm, y=call_mid_price, k=degree)  # call_mid_price does not matter
    B = bspl.design_matrix(x=joint_strikes_norm, t=bspl.t, k=degree, extrapolate=False).toarray()
    t_knots = bspl.t
    if verbose:
        print(f"{t_knots}\n{t_knots}")
        print(f"p=\n{B}")
        print(f"len(x)= {len(joint_strikes_norm)}, len(t_knots)={len(t_knots)}, B.shape={B.shape}")

    # set optimisation problem
    n = len(joint_strikes_norm)
    n2 = 2*n
    z = cvx.Variable(n2, nonneg=True)
    G, D2 = set_matrix_g(x=joint_strikes_norm)
    WB_call = weight_calls @ B
    Q_call = cvx.psd_wrap(np.transpose(WB_call) @ WB_call)
    q_call = - WB_call @ call_mid_price

    WB_put = weight_puts @ B
    Q_put = cvx.psd_wrap(np.transpose(WB_put) @ WB_put)
    q_put = - WB_put @ put_mid_price

    # model calls and puts
    model_calls = B @ z[:n]
    model_puts = B @ z[n:]

    # monotonicity constraints
    h1 = -eps*np.ones(n)
    h2 = -eps*np.ones(n)
    h1[0] = discfactor - eps
    h2[-1] = discfactor - eps
    constraints = [G @ model_calls <= h1]
    constraints = constraints + [G @ model_puts <= h2]
    # constraints = constraints + [(D2 @ B) @ z[:n] >= 0.0]
    # constraints = constraints + [(D2 @ B) @ z[n:] >= 0.0]

    diff1, diff2 = set_matrix_diff1_diff2(x=joint_strikes_norm)
    constraints = constraints + [diff1 @ z[:n] <= eps]   # monotonic
    constraints = constraints + [diff1 @ z[n:] >= eps]   # monotonic

    # put call parity
    call_put_rhs = discfactor * (forward_price / norm_factor - joint_strikes_norm)
    bid_ask_spreads = 0.5 * (call_bid_ask_spread.to_numpy() + put_bid_ask_spread.to_numpy())
    call_put_parity_constraints = []

    for idx, is_valid in enumerate(is_call_put_available):
        if is_valid > 0.0:  # put index is shifted by n
            call_put_parity_constraints += [-bid_ask_spreads[idx] <= model_calls[idx] - model_puts[idx] - call_put_rhs[idx]]
            call_put_parity_constraints += [bid_ask_spreads[idx] >= model_calls[idx] - model_puts[idx] - call_put_rhs[idx]]
    constraints = constraints + call_put_parity_constraints

    if is_add_bid_ask_constraint:
        call_constraints = []
        call_bids = np.maximum((1.0-bid_ask_contraint_band)*call_bid_prices.to_numpy(), 0.0)
        call_asks = (1.0 + bid_ask_contraint_band) * call_ask_prices.to_numpy()
        for idx, (is_call_available_, call_bid, call_ask) in enumerate(zip(is_call_available, call_bids, call_asks)):
            if is_call_available_ > 0:
                call_constraints += [model_calls[idx] >= call_bid]
                call_constraints += [model_calls[idx] <= call_ask]

        put_constraints = []
        put_bids = np.maximum((1.0-bid_ask_contraint_band)*put_bid_prices.to_numpy(), 0.0)
        put_asks = (1.0 + bid_ask_contraint_band) * put_ask_prices.to_numpy()
        for idx, (is_put_available_, put_bid, put_ask) in enumerate(zip(is_put_available, put_bids, put_asks)):
            if is_put_available_ > 0:  # puts are shifted by n
                put_constraints += [model_puts[idx] >= put_bid]
                put_constraints += [model_puts[idx] <= put_ask]

        constraints = constraints + call_constraints + put_constraints

    # total objective_fun
    dk = np.concatenate((np.array([0.0]), np.reciprocal(joint_strikes_norm[1:] - joint_strikes_norm[:-1])))
    p_sline_conv = G @ z[:n] + G @ z[n:]
    convexity_objective = cvx.norm(p_sline_conv, 2)
    objective_fun = (1.0/(n2*n2))*(0.5*cvx.quad_form(z[:n], Q_call) + q_call @ z[:n] + 0.5*cvx.quad_form(z[n:], Q_put) + q_put @ z[n:]) + 1e-12*convexity_objective
    objective = cvx.Minimize(objective_fun)
    problem = cvx.Problem(objective, constraints)
    try:
        kwargs = dict(max_iters=20000, feastol=1e-12, abstol=1e-12, reltol=1e-16)
        # problem.solve(solver=cvx.ECOS, verbose=verbose, **kwargs)
        # problem.solve(solver=cvx.ECOS_BB, verbose=True, **kwargs)
        # problem.solve(solver=cvx.DAQP, verbose=True)
        problem.solve(solver=cvx.CLARABEL, verbose=True)
        # problem.solve(verbose=verbose)
        option_marks = z.value
    except cvx.error.SolverError:
        option_marks = None
    if option_marks is not None:
        b_call = norm_factor*option_marks[:n]
        b_put = norm_factor*option_marks[n:]
        call_marks = B @ b_call
        put_marks = B @ b_put
        call_marks = pd.Series(np.maximum(call_marks, 1e-16), index=joint_strikes, name='calls')
        put_marks = pd.Series(np.maximum(put_marks, 1e-16), index=joint_strikes, name='puts')
        bspl0 = make_interp_spline(x=joint_strikes, y=call_mid_price, k=degree)  # call_mid_price does not matter
        call_spline = BSpline(t=bspl0.t, c=b_call, k=degree, extrapolate=False)
        put_spline = BSpline(t=bspl0.t, c=b_put, k=degree, extrapolate=False)

    else:
        print(f"problem is not solved, try to decrease smootheness eps={eps}")
        call_marks, put_marks, call_spline, put_spline = None, None, None, None

    return call_marks, put_marks, call_spline, put_spline


def estimate_b_spline(x: np.ndarray,
                      y: np.ndarray,
                      degree: int = 3,
                      eps: float = 1e-3,
                      verbose: bool = True
                      ) -> BSpline:
    """
    compute t_knots and spline coeffs
    """
    # Compute the (coefficients of) interpolating B-spline
    bspl = make_interp_spline(x, y, k=degree)  #, bc_type="natural"
    B = bspl.design_matrix(x, bspl.t, k=degree, extrapolate=False).toarray()
    t_knots = bspl.t
    if verbose:
        print(f"{t_knots}\n{t_knots}")
        print(f"p=\n{B}")
        print(f"len(x)= {len(x)}, len(t_knots)={len(t_knots)}, B.shape={B.shape}")

    # Q = cvx.psd_wrap(np.transpose(B) @ B)
    Q = np.transpose(B) @ B
    q = - np.transpose(B) @ y
    n = x.shape[0]
    z = cvx.Variable(n, nonneg=True)

    G, D2 = set_matrix_g(x=x)
    D1, D2 = set_matrix_d1_d2(x=x)

    h1 = -eps*np.ones(n)
    h1[0] = 1.0 - eps
    # h1[-1] = 0.0
    constraints = [(G @ B) @ z <= h1]
    # constraints = constraints + [(D1 @ B) @ z <= -eps] derivative
    constraints = constraints + [(D2 @ B) @ z >= 0.0]
    diff1, diff2 = set_matrix_diff1_diff2(x=x)
    #constraints = constraints + [diff1 @ z <= -eps]   # monotonic
    # constraints = constraints + [diff2 @ z >= 0.0]  # monotonic

    objective_fun = 0.5*cvx.quad_form(z, Q) + q @ z
    objective = cvx.Minimize(objective_fun)

    problem = cvx.Problem(objective, constraints)
    kwargs = dict(tol_feas=1e-12)
    problem.solve(solver=cvx.CLARABEL, verbose=True)
    # problem.solve(verbose=True)
    spline_coeffs = z.value

    print('spline_coeffs')
    print(spline_coeffs)
    print(f"monotonic={np.all(spline_coeffs[1:] < spline_coeffs[:-1])}")
    # spl = BSpline(t=t_knots, c=spline_coeffs, k=degree, extrapolate=False)
    bspl.c = spline_coeffs
    return bspl


class UnitTests(Enum):
    RUN_B_SPLINE = 1


def run_unit_test(unit_test: UnitTests):

    import matplotlib.pyplot as plt
    np.random.seed(5)

    x = np.linspace(0.1, 2.1, 25)
    x1 = np.linspace(0.1, 2.0, 100)
    # x1 = np.array([0.25, 0.41, 0.64, 0.71, 0.79, 0.81, 1.02, 1.23, 1.24, 1.46, 1.50, 1.53, 1.70, 1.9])
    # x1 = x
    noise = 0.001*np.random.normal(0.0, 1.0, size=x.shape[0])
    y = 1.0 / (1.0+np.sqrt(x))
    y_noise = y + noise
    yy = pd.concat([pd.Series(y, index=x, name='y'), pd.Series(y_noise, index=x, name='y_noise')], axis=1)

    if unit_test == UnitTests.RUN_B_SPLINE:

        t_knots, spline_coeffs = estimate_b_spline(x=x, y=y_noise, is_monotonic=False)
        y_spline1 = bspline_interpolation(x=x1, t_knots=t_knots, spline_coeffs=spline_coeffs)
        y_spline1 = pd.Series(y_spline1, index=x1, name='y_spline')

        t_knots, spline_coeffs = estimate_b_spline(x=x, y=y_noise, is_monotonic=True)
        y_spline2 = bspline_interpolation(x=x1, t_knots=t_knots, spline_coeffs=spline_coeffs)
        y_spline2 = pd.Series(y_spline2, index=x1, name='y_spline monotonic')

        df = pd.concat([yy, y_spline1, y_spline2], axis=1).sort_index()
        print(df)
        qis.plot_line(df=df)

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.RUN_B_SPLINE

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
