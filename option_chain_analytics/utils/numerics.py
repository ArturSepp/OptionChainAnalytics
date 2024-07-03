
import numpy as np
import pandas as pd
from numba import njit
from typing import Tuple


@njit
def set_matrix_d1_d2(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
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
            d1[n, 0] = d_right
            d1[n, 1] = - d_right
        elif n == nn - 1:
            d_left = 1.0 / (x[n] - x[n - 1])
            d1[n, nn-2] = - d_left
            d1[n, nn-1] = d_left
        else:
            d_left = 1.0 / (x[n] - x[n - 1])
            d_right = 1.0 / (x[n + 1] - x[n])
            d_left_right = 1.0 / (x[n + 1] - x[n - 1])
            d1[n, n - 1] = - d_left
            d1[n, n] = d_left + d_right
            d1[n, n + 1] = - d_right

            d2[n, n - 1] = 2.0 * d_left * d_left_right
            d2[n, n] = - 2.0 * d_left * d_right
            d2[n, n + 1] = 2.0 * d_right * d_left_right

    return d1, d2


def compute_pdf_from_prices(option_prices: pd.Series, is_call: bool = True) -> Tuple[pd.Series, pd.Series]:
    d1, d2 = set_matrix_d1_d2(x=option_prices.index.to_numpy())
    option_prices_np = option_prices.to_numpy()
    strikes_np = option_prices.index.to_numpy()
    d_k = (option_prices_np[1:] - option_prices_np[:-1]) / (strikes_np[1:] - strikes_np[:-1])
    if is_call:
        d_k = 1.0 - np.concatenate((np.array([1.0]), -d_k))
    else:
        d_k = np.concatenate((d_k, np.array([1.0])))
    d_k = pd.Series(d_k, index=option_prices.index)
    d_kk = pd.Series(d2 @ option_prices_np, index=option_prices.index)
    return d_k, d_kk
