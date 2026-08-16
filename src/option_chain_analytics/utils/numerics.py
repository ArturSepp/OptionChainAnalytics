
from typing import Tuple

import numpy as np
import pandas as pd
from numba import njit


@njit
def set_matrix_g(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    compute the matrix g for price spline and d2
    loop is optimised with njit
    """
    nn = x.shape[0]
    g = np.zeros((nn, nn))
    d2 = np.zeros((nn, nn))
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
            d_left_right = 1.0 / (x[n + 1] - x[n - 1])

            g[n, n - 1] = - d_left
            g[n, n] = d_left + d_right
            g[n, n + 1] = - d_right

            d2[n, n - 1] = 2.0 * d_left * d_left_right
            d2[n, n] = - 2.0 * d_left * d_right
            d2[n, n + 1] = 2.0 * d_right * d_left_right

    return g, d2


@njit
def set_matrix_d1_d2(x: np.ndarray, is_one_sided: bool = True) -> Tuple[np.ndarray, np.ndarray]:
    """
    compute the matrix d1 and d2 for partial derivatives in x grid
    loop is optimised with njit
    """
    nn = x.shape[0]
    d1 = np.zeros((nn, nn))
    d2 = np.zeros((nn, nn))
    for n in np.arange(nn):
        if n == 0:
            d_right = 1.0 / (x[n + 1] - x[n])
            d1[n, 0] = - d_right
            d1[n, 1] = d_right
        elif n == nn - 1:
            d_left = 1.0 / (x[n] - x[n - 1])
            d1[n, nn-2] = - d_left
            d1[n, nn-1] = d_left
        else:
            d_left = 1.0 / (x[n] - x[n - 1])
            d_right = 1.0 / (x[n + 1] - x[n])
            d_left_right = 1.0 / (x[n + 1] - x[n - 1])
            if is_one_sided:
                d1[n, n - 1] = - d_left
                d1[n, n] = d_left
            else:
                d1[n, n - 1] = - d_left_right
                d1[n, n + 1] = d_left_right

            d2[n, n - 1] = 2.0 * d_left * d_left_right
            d2[n, n] = - 2.0 * d_left * d_right
            d2[n, n + 1] = 2.0 * d_right * d_left_right

    return d1, d2

@njit
def set_matrix_diff1_diff2(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    compute the matrix f partial derivatives without using dx
    loop is optimised with njit
    """
    nn = x.shape[0]
    diff1 = np.zeros((nn, nn))
    diff2 = np.zeros((nn, nn))
    for n in np.arange(nn):
        if n == 0:
            diff1[n, 0] = -1.0
            diff1[n, 1] = 1.0
        elif n == nn - 1:
            diff1[n, nn-2] = -1.0
            diff1[n, nn-1] = 1.0
        else:
            diff1[n, n-1] = -1.0
            diff1[n, n] = 1.0

            diff2[n, n - 1] = 1.0
            diff2[n, n] = -2.0
            diff2[n, n + 1] = 1.0
    return diff1, diff2


def compute_pdf_from_prices(option_prices: pd.Series, is_call: bool = True) -> Tuple[pd.Series, pd.Series]:
    d1, d2 = set_matrix_d1_d2(x=option_prices.index.to_numpy(), is_one_sided=True)
    option_prices_np = option_prices.to_numpy()
    d_k = d1 @ option_prices_np
    if is_call:
        d_k = 1.0 + d_k
    else:
        d_k = d_k
    d_k = pd.Series(d_k, index=option_prices.index)
    d_kk = pd.Series(d2 @ option_prices_np, index=option_prices.index)
    return d_k, d_kk

