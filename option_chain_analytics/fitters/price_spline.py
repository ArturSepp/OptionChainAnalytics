"""
fit spline to prices
example usage in volatility_book/ch_implied_vol/fit_price_spline
"""
import pandas as pd
import numpy as np
import cvxpy as cvx
from numba import njit
from typing import Optional
from enum import Enum
from option_chain_analytics.option_chain import SliceColumn


class WeightType(Enum):
    IDENTITY = 1
    TIME_VALUE = 2
    BID_ASK_SPREAD = 3
    ABS_MONEYNESS = 4


@njit
def set_matrix_g(x: np.ndarray) -> np.ndarray:
    """
    compute the matrix f partial derivatives
    loop is optimised with njit
    """
    nn = x.shape[0]
    g = np.zeros((nn, nn))
    for n in np.arange(nn):
        if n == 0:
            d_right = 1.0 / (x[n + 1] - x[n])
            g[n, 0] = d_right
            g[n, 1] = - d_right
        elif n == nn - 1:
            d_left = 1.0 / (x[n] - x[n - 1])
            g[n, nn-2] = - d_left
            g[n, nn-1] = d_left
        else:
            d_left = 1.0 / (x[n] - x[n - 1])
            d_right = 1.0 / (x[n + 1] - x[n])
            g[n, n - 1] = - d_left
            g[n, n] = d_left + d_right
            g[n, n + 1] = - d_right
    return g


@njit
def set_matrix_g1(x: np.ndarray) -> np.ndarray:
    """
    compute the matrix f partial derivatives
    loop is optimised with njit
    """
    nn = x.shape[0]
    g = np.zeros((nn, nn))
    for n in np.arange(nn):
        if n == 0:
            g[n, 0] = -1
            g[n, 1] = 1
        elif n == nn - 1:
            g[n, nn-2] = -1
            g[n, nn-1] = 1
        else:
            g[n, n] = -1
            g[n, n + 1] = 1
    return g


def infer_mark_price_with_spline(option_slice: pd.DataFrame,
                                 spot_price: float,
                                 eps: float = 1e-8,
                                 is_calls: bool = True,
                                 weight_type: WeightType = WeightType.TIME_VALUE,
                                 verbose: bool = True
                                 ) -> Optional[pd.Series]:

    # set zeros to nans
    mid_price = 0.5*(option_slice[SliceColumn.BID_PRICE.value].replace({0.0: np.nan})
                     + option_slice[SliceColumn.BID_PRICE.value].replace({0.0: np.nan}))
    # exclude prices where one quote is nan
    option_slice = option_slice.loc[np.isnan(mid_price) == False, :]
    n = len(option_slice.index)
    bid_price = option_slice[SliceColumn.BID_PRICE.value].to_numpy()
    ask_price = option_slice[SliceColumn.ASK_PRICE.value].to_numpy()
    strikes = option_slice[SliceColumn.STRIKE.value].to_numpy()

    # set error weights
    if weight_type == WeightType.IDENTITY:
        w = np.identity(n)
    elif weight_type == WeightType.TIME_VALUE:
        mid_price = 0.5 * (bid_price + ask_price)
        # floor time_value to 1e-8
        if is_calls:
            time_value = np.maximum(mid_price - np.maximum(spot_price-strikes, 0.0), 1e-8)
        else:
            time_value = np.maximum(mid_price - np.maximum(strikes-spot_price, 0.0), 1e-8)

        # filter out potential outliers in the tails
        # find max time value around at - region
        atm_spot_index = np.absolute(strikes-spot_price).argmin()
        atm_time_value = np.max(time_value[atm_spot_index-2:atm_spot_index+2])

        # ensure that intrinsic values are declining
        # right side
        last_time_value = atm_time_value
        for n_ in np.arange(atm_spot_index, 0, step=-1):
            if time_value[n_] > last_time_value: # use last_time_value for backfill don't update last_time_value
                time_value[n_] = last_time_value
            else:
                last_time_value = time_value[n_]
        # left side
        last_time_value = atm_time_value
        for n_ in np.arange(atm_spot_index, n):
            if time_value[n_] > last_time_value: # use last_time_value for backfill don't update last_time_value
                last_time_value *= 0.5  # penalise for a sequence of outliers
                time_value[n_] = last_time_value
            else:
                last_time_value = time_value[n_]
        w = np.diag(time_value)

    elif weight_type == WeightType.ABS_MONEYNESS:
        abs_m = np.maximum(np.abs(strikes-spot_price), 1e-8)
        w = np.diag(np.reciprocal(abs_m))

    elif weight_type == WeightType.BID_ASK_SPREAD:
        spread = (ask_price - bid_price)
        w = np.diag(np.reciprocal(spread))
    else:
        raise NotImplementedError(f"weight_type={weight_type}")

    # set optimisation problem
    z = cvx.Variable(n)
    G = set_matrix_g(x=strikes)
    h = -eps*np.ones(n)
    Q = np.transpose(w) @ w
    q = - Q @ mid_price
    if is_calls:
        h[0] = 1.0 - eps
        constraints = [G @ z <= h]
    else:
        h[-1] = - 1.0 + eps
        constraints = [G @ z <= - h]

    # start solver
    objective_fun = 0.5*cvx.quad_form(z, Q) + q @ z
    objective = cvx.Minimize(objective_fun)
    problem = cvx.Problem(objective, constraints)
    try:
        problem.solve(verbose=verbose)
        call_marks = z.value
    except cvx.error.SolverError:
        call_marks = None
    if call_marks is not None:
        call_marks = pd.Series(call_marks, index=strikes, name=SliceColumn.MARK_PRICE)
    else:
        print(f"problem is not solved, try to decrease smootheness eps={eps}")
    return call_marks


# @njit
def compute_t_knots(x: np.ndarray, degree: int = 3) -> np.ndarray:
    """
    compute t_knots for b-spline
    default is degree = 3
    #
    """
    n = x.shape[0]
    n_knots = n + 4
    # compute nodes
    t_knots = np.zeros(n_knots)
    for n_ in np.arange(0, n-1):
        #t_knots[n_+3] = 0.5*(x[n_+2]+x[n_+1])
        # t_knots[n_ + 2] = 0.5 * (x[n_ - 1] + x[n_])
        t_knots[n_ + 2] = x[n_]
    t_knots[0] = t_knots[1] = t_knots[2] = x[0]
    t_knots[n+1] = t_knots[n+2] = t_knots[n+3] = x[n-1]
    print(x)
    print(t_knots)
    return t_knots


#@njit
def B1(x: float, i: int, t_knots: np.ndarray, degree: int = 3) -> float:
    """
    b-spline polynomial
    """
    if degree == 0:
        return 1.0 if t_knots[i] <= x < t_knots[i + 1] else 0.0
    if t_knots[i + degree] == t_knots[i]:
        c1 = 0.0
    else:
        c1 = (x - t_knots[i]) / (t_knots[i + degree] - t_knots[i]) * B(x, i, t_knots, degree - 1)
    if t_knots[i + degree + 1] == t_knots[i + 1]:
        c2 = 0.0
    else:
        c2 = (t_knots[i + degree + 1] - x) / (t_knots[i + degree + 1] - t_knots[i + 1]) * B(x, i + 1, t_knots, degree - 1)
    return c1 + c2


#@njit
def B(x: float, i: int, t_knots: np.ndarray) -> float:
    """
    i runs from 2 to n-3
    """
    h = t_knots[4]-t_knots[3]
    h2 = h*h
    h3 = h2*h
    if t_knots[i-2] <= x < t_knots[i-1]:
        b = np.power(x-t_knots[i-2], 3)
    elif t_knots[i-1] <= x < t_knots[i]:
        dx = x-t_knots[i-1]
        dx2 = dx*dx
        dx3 = dx2*dx
        b = -3.0*dx3 + 3.0*h*dx2 + 3.0*h2*dx+h3
    elif t_knots[i] <= x < t_knots[i+1]:
        dx = t_knots[i+1] - x
        dx2 = dx*dx
        dx3 = dx2*dx
        b = -3.0*dx3 + 3.0*h*dx2 + 3.0*h2*dx+h3
    elif t_knots[i+1] <= x < t_knots[i+2]:
        b = np.power(t_knots[i + 2] - x, 3)
    else:
        b = 0.0
    return b / (6.0*h3)


# @njit
def bspline_interpolation(x: np.ndarray, t_knots: np.ndarray, spline_coeffs: np.ndarray, degree: int = 3) -> np.ndarray:
    """
    given input array x
    t_knots and spline coefficients spline_coeffs
    compute spline interpolation
    """
    n = len(t_knots) #- degree - 1
    # assert (n >= degree+1) and (len(spline_coeffs) >= n)
    y_spline = np.zeros_like(x)
    for idx, x_ in enumerate(x):
        sums = 0.0
        bb = np.zeros(n)
        for i in np.arange(1, n-2):
            bb[i] = B(x_, i=i, t_knots=t_knots)
            sums += spline_coeffs[i] * B(x_, i=i, t_knots=t_knots)
        print(f"idx={idx}: {bb}")
        y_spline[idx] = sums
    return y_spline


@njit
def compute_p_matrix0(x: np.ndarray, t_knots: np.ndarray, degree: int = 3) -> np.ndarray:
    n = x.shape[0]
    p = np.zeros((n, n))
    for i in np.arange(n):
        for j in np.arange(n):
            p[i, j] = B(x=x[j], i=i, t_knots=t_knots, degree=degree, is_natural_boundaries=False)
    return p


def compute_p_matrix(x: np.ndarray, t_knots: np.ndarray, degree: int = 3) -> np.ndarray:
    n = x.shape[0]  # neew two extra points
    a = np.ones(n-1)
    b = 4.0*np.ones(n)
    c = np.ones(n-1)
    m = np.diag(a, -1) + np.diag(b, 0) + np.diag(c, 1)  # chape = n
    m[0, 0], m[0, 1], m[0, 2] = 1.0, 1.0, 1.0
    m[n-1, n-1], m[n-1, n-2] , m[n-1, n-3] = 1.0, 1.0, 1.0
    #m[0, 0], m[0, 1], m[0, 2] = 1.0, -2.0, 1.0
    #m[n-1, n-1], m[n-1, n-2] , m[n-1, n-3] = 1.0, -2.0, 1.0
    return m


def compute_b_spline(x: np.ndarray, y: np.ndarray, degree: int = 3, eps: float = 1e-3, is_monotonic: bool = True):
    """
    compute t_knots and spline coeffs
    """
    t_knots = compute_t_knots(x=x, degree=degree)
    # compute b-spline matrix P[i,j]
    x = np.concatenate((np.array([x[0]]), x, np.array([x[-1]])))
    y = 6.0*np.concatenate((np.array([0.5*y[0]]), y, np.array([0.5*y[-1]])))
    p = compute_p_matrix(x=x, t_knots=t_knots, degree=degree)

    Q = np.transpose(p) @ p
    q = - np.transpose(p) @ y
    n = x.shape[0]
    z = cvx.Variable(n)
    # start solver
    objective_fun = 0.5*cvx.quad_form(z, Q) + q @ z
    objective = cvx.Minimize(objective_fun)

    G = set_matrix_g1(x=x)
    h = -eps*np.ones(n)
    #h[0] = 0.0
    #h[-1] = 0.0

    constraints = []
    if is_monotonic:
        constraints = constraints + [G @ z <= h]

    problem = cvx.Problem(objective, constraints)
    problem.solve(verbose=True)
    spline_coeffs = z.value
    spline_coeffs = np.concatenate((np.array([2.0*spline_coeffs[0]-spline_coeffs[1]]),
                                    spline_coeffs,
                                    np.array([2.0*spline_coeffs[-1]-spline_coeffs[-2]])))
    print('spline_coeffs')
    print(spline_coeffs)

    return t_knots, spline_coeffs


class UnitTests(Enum):
    RUN_B_SPLINE = 1


def run_unit_test(unit_test: UnitTests):

    import matplotlib.pyplot as plt
    import qis as qis
    np.random.seed(4)

    x = np.linspace(0.1, 2.1, 25)
    x1 = np.linspace(0.1, 2.0, 100)
    # x1 = x
    noise = 0.05*np.random.normal(0.0, 1.0, size=x.shape[0])
    y = 1.0 / (1.0+np.sqrt(x))
    y_noise = y + noise
    yy = pd.concat([pd.Series(y, index=x, name='y'), pd.Series(y_noise, index=x, name='y_noise')], axis=1)

    if unit_test == UnitTests.RUN_B_SPLINE:

        t_knots, spline_coeffs = compute_b_spline(x=x, y=y_noise, is_monotonic=False)
        y_spline1 = bspline_interpolation(x=x1, t_knots=t_knots, spline_coeffs=spline_coeffs)
        y_spline1 = pd.Series(y_spline1, index=x1, name='y_spline')

        t_knots, spline_coeffs = compute_b_spline(x=x, y=y_noise, is_monotonic=True)
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

