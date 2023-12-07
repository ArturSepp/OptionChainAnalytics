"""
utility functions
"""
import numpy as np
from numba import njit
from typing import Union

from scipy.integrate import quad

ONE_OVER_SQRT_TWO_PI = 0.3989422804014327
ONE_OVER_SQRT_TWO = 0.7071067811865475


@njit(cache=False, fastmath=True)
def erfcc(x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    """
    Complementary error function
    """
    z = np.abs(x)
    t = 1. / (1. + 0.5*z)
    r = t * np.exp(-z*z-1.26551223+t*(1.00002368+t*(0.37409196+t*(0.09678418+t*(-0.18628806+t*(0.27886807+
        t*(-1.13520398+t*(1.48851587+t*(-.82215223+t*0.17087277)))))))))
    fcc = np.where(np.greater(x, 0.0), r, 2.0-r)
    return fcc


@njit(cache=False, fastmath=True)
def ncdf(x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    return 1.0 - 0.5*erfcc(ONE_OVER_SQRT_TWO*x)


@njit(cache=False, fastmath=True)
def npdf(x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    return np.exp(-0.5*np.square(x))/np.sqrt(2.0*np.pi)


@njit
def range_prob_t(t: float, vol: float, xa: float, xb: float) -> float:
    vol_st = vol * np.sqrt(t)
    da = xa / vol_st + 0.5*vol_st
    db = xb / vol_st + 0.5*vol_st
    return ncdf(db) - ncdf(da)


def compute_int_range_prob(t: float, vol: float, p0: float, pa: float, pb: float):
    xa = np.log(pa / p0)
    xb = np.log(pb / p0)

    def func(t_: float) -> float:
        return range_prob_t(t=t_, vol=vol, xa=xa, xb=xb)

    return quad(func, a=1e-16, b=t)[0] / t
