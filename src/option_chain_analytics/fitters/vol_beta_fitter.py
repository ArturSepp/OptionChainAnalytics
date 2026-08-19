"""Legacy approximate LogSV smile analytics.

TODO: Move the provider-independent LogSV smile, density, and synthetic-price
analytics to StochVolModels, update SigmaStrats' LP hedger to import them there,
and leave OCA responsible only for normalized option-chain data.
"""
from enum import Enum
from typing import Dict, Optional, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import vanilla_option_pricers as bsm
from scipy.optimize import brenth, curve_fit
from scipy.stats import norm

FUTURES = 'futures'
ATM_VOL = 'sigma0'
BETA = 'beta'
VOLVOL = 'volvol'


def cals_logsv_atm_fit(log_strikes: np.ndarray,
                       mid_vols: np.ndarray,
                       strike_step: float = 0.3
                       ) -> Dict[str, float]:
    """
    compute atm fit for beta for initial guesses for optimisation
    """
    atm_vol = np.interp(x=0.0, xp=log_strikes, fp=mid_vols)
    atm_vol_m1 = np.interp(x=-strike_step, xp=log_strikes, fp=mid_vols)
    atm_vol_p1 = np.interp(x=strike_step, xp=log_strikes, fp=mid_vols)
    beta = (atm_vol_m1 - atm_vol_p1) / (2.0 * strike_step)
    convexity = np.maximum((atm_vol_m1 - 2.0 * atm_vol + atm_vol_p1) / (strike_step * strike_step), 0.01)
    volvol = np.sqrt(0.5 * (12.0 * (convexity * atm_vol) + beta * beta))
    atm_fit_params = {ATM_VOL: atm_vol, BETA: beta, VOLVOL: volvol}
    return atm_fit_params


def fit_logsv_ivols(log_strikes: np.ndarray,
                    mid_vols: np.ndarray,
                    ttm: float,
                    is_vega_weights: bool = True
                    ) -> Dict[str, float]:
    """
    fit logsv vol for zero mean-reversion
    """
    bounds = ([0.01, -15.0, 0.01], [np.nanmax(mid_vols), 5.0, 30.0])
    atm_fit_params = cals_logsv_atm_fit(log_strikes=log_strikes, mid_vols=mid_vols)
    # p0 = np.array([atm_fit_params[ATM_VOL], atm_fit_params[BETA], atm_fit_params[VOLVOL]])
    p0 = np.array([atm_fit_params[ATM_VOL], 0.0, 0.1])

    # f(x; params)
    def func(log_strikes, sigma0, beta, volvol):
        return calc_logsv_ivols(log_strikes, sigma0, beta, volvol)

    # sigma is the inverse of vega weights
    if is_vega_weights:
        vol = mid_vols * np.sqrt(ttm)
        d1 = -log_strikes / vol + 0.5 * vol
        vega = np.sqrt(ttm) * np.exp(-0.5 * d1 * d1)
        sigma = np.reciprocal(vega)
    else:
        sigma = None
    popt, pcov = curve_fit(f=func,
                           xdata=log_strikes,
                           ydata=mid_vols,
                           bounds=bounds,
                           p0=p0,
                           sigma=sigma)
    fit_params = {ATM_VOL: popt[0], BETA: popt[1], VOLVOL: popt[2]}
    return fit_params


def calc_logsv_ivols(log_strikes: Union[float, np.ndarray],
                     sigma0: float,
                     beta: float,
                     volvol: float,
                     is_quadratic: bool = True
                     ) -> Union[float, np.ndarray]:
    y = - log_strikes / sigma0
    # for approximation near zero
    b = - beta / 2.0
    c = 2.0 * volvol * volvol - beta * beta
    quadratic_ivols = sigma0 * (1.0 + (b + c * y) * y)
    if is_quadratic:
        return quadratic_ivols
    else:
        vartheta2 = beta * beta + volvol * volvol
        vartheta = np.sqrt(vartheta2)
        j_y = np.sqrt(1.0 + vartheta2 * y * y - 2.0 * beta * y)
        x = (1.0 / vartheta) * np.log((j_y * vartheta + vartheta2 * y - beta) / (vartheta - beta))
        ivols = np.divide(y, x, where=np.greater(np.abs(x), 0.0))
        ivols = np.where(np.greater(np.abs(x), 0.0), ivols,  quadratic_ivols)
    return ivols


def calc_logsv_ivols_partials(log_strikes: np.ndarray,
                              sigma0: float,
                              beta: float,
                              volvol: float,
                              eps: float = 0.01,
                              mult: float = 1.0,
                              is_analytic: bool = False
                              ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not is_analytic:
        def sigma(x: np.ndarray) -> np.ndarray:
            return calc_logsv_ivols(log_strikes=x, sigma0=sigma0, beta=beta, volvol=volvol)

        sigma_0 = sigma(x=log_strikes)
        sigma_p = sigma(x=log_strikes + eps)
        sigma_m = sigma(x=log_strikes - eps)
        dsigma = (0.5 / eps) * (sigma_p - sigma_m)
        d2sigma = (1.0 / (eps * eps)) * (sigma_p - 2.0 * sigma_0 + sigma_m)
        return mult * sigma_0, mult * dsigma, mult * d2sigma
    else:
        y = - log_strikes / sigma0
        vartheta2 = beta * beta + volvol * volvol
        vartheta = np.sqrt(vartheta2)
        j_y = np.sqrt(1.0 + vartheta2 * y * y - 2.0 * beta * y)
        log_y = np.log((j_y * vartheta + vartheta2 * y - beta) / (vartheta - beta))
        impvol = sigma0 * y / (1 / vartheta * log_y)
        DimpvolDy = -vartheta2 * sigma0 * y / (j_y * log_y * log_y) + sigma0 * vartheta / log_y
        D2impvolDy2 = vartheta2 * sigma0 * (2 * y * vartheta * j_y - (j_y * j_y - y * beta + 1) * log_y) / np.power(
            j_y * log_y, 3.0)
        DimpvolDk = DimpvolDy * (-1.0 / sigma0)
        D2impvolDk2 = D2impvolDy2 * (1.0 / sigma0 / sigma0)
        return mult * impvol, mult * DimpvolDk, mult * D2impvolDk2


def calc_logsv_pdf(ttm: float,
                   sigma0: float,
                   beta: float,
                   volvol: float,
                   log_strikes: Optional[np.ndarray] = None,
                   is_norm: bool = False,
                   cut: float = 6.0,
                   is_analytic: bool = False
                   ) -> pd.Series:

    pdf = calc_logsv_pdf_core(ttm=ttm,
                              sigma0=sigma0,
                              beta=beta,
                              volvol=volvol,
                              log_strikes=log_strikes,
                              is_norm=is_norm,
                              cut=cut,
                              is_analytic=is_analytic)

    if is_norm:
        dx = log_strikes[1] - log_strikes[0]
        pdf = dx * pdf

    return pdf


def calc_logsv_pdf_core(ttm: float,
                        sigma0: float,
                        beta: float,
                        volvol: float,
                        log_strikes: Optional[np.ndarray] = None,
                        is_norm: bool = False,
                        cut: float = 6.0,
                        is_analytic: bool = False
                        ) -> pd.Series:

    """
    compute pdf
    """
    vol_t = sigma0 * np.sqrt(ttm)

    if log_strikes is None:
        log_strikes = np.linspace(-cut * vol_t, cut * vol_t, 100)

    sigma_0, dsigma, d2sigma = calc_logsv_ivols_partials(log_strikes=log_strikes,
                                                         sigma0=sigma0,
                                                         beta=beta,
                                                         volvol=volvol,
                                                         eps=0.001,
                                                         mult=np.sqrt(ttm),
                                                         is_analytic=is_analytic)
    f1 = log_strikes / sigma_0 - 0.5 * sigma_0
    f2 = log_strikes / sigma_0 + 0.5 * sigma_0
    df1 = (1.0-dsigma*f2)/sigma_0
    df2 = (1.0 - dsigma * f1) / sigma_0
    pdf = norm.pdf(f2) * (sigma_0*df1*df2 + d2sigma)
    return pd.Series(pdf, index=log_strikes)


def infer_strikes_from_deltas(deltas: np.ndarray,
                              forward: float,
                              ttm: float,
                              sigma0: float,
                              beta: float,
                              volvol: float
                              ) -> pd.Series:
    """
    givem
    """
    st = np.sqrt(ttm)

    def func(strike: float, given_delta: float) -> float:
        log_strike = np.log(strike / forward)
        vol_st = st * calc_logsv_ivols(log_strikes=log_strike, sigma0=sigma0, beta=beta, volvol=volvol)
        if given_delta >= 0.0:
            target = norm.ppf(given_delta)
        else:
            target = norm.ppf(1.0+given_delta)
        f = -log_strike / vol_st + 0.5 * vol_st - target
        return f

    imp_deltas = {}
    for idx, given_delta in enumerate(deltas):
        try:
            strike = brenth(f=func, a=0.0001 * forward, b=200.0 * forward, args=(given_delta))  # , x0=forward
        except:
            print(f"can't find strike for delta={given_delta}, ttm={ttm}, forward={forward}")
            strike = forward
        imp_deltas[given_delta] = strike

    imp_deltas = pd.DataFrame.from_dict(imp_deltas, orient='index')
    return imp_deltas.iloc[:, 0]


def get_vols_delta_space(forward: float,
                         ttm: float,
                         sigma0: float,
                         beta: float,
                         volvol: float,
                         deltas: Optional[np.ndarray] = None,
                         is_remap_to_str_delta: bool = True
                         ) -> pd.Series:
    if deltas is None:
        deltas = np.linspace(0.01, 0.99, 100)

    imp_strikes = infer_strikes_from_deltas(deltas=deltas,
                                            forward=forward,
                                            ttm=ttm,
                                            sigma0=sigma0,
                                            beta=beta,
                                            volvol=volvol)
    log_strikes = np.log(imp_strikes.to_numpy() / forward)
    vols = calc_logsv_ivols(log_strikes=log_strikes, sigma0=sigma0, beta=beta, volvol=volvol)
    vols = pd.Series(vols, index=deltas).sort_index()
    if is_remap_to_str_delta:
        put_cond = vols.index > 0.5
        put_vols = vols[put_cond]
        put_vols.index = [x-1.0 for x in put_vols.index]
        put_vols=put_vols.sort_index(ascending=False)
        call_vols = vols[put_cond == False].sort_index(ascending=False)
        put_vols.index = [f"{x:0.2f}" for x in put_vols.index]
        call_vols.index = [f"{x:0.2f}" for x in call_vols.index]
        vols = pd.concat([put_vols, call_vols], axis=0)
    return vols


def get_pdf_delta_space(forward: float,
                        ttm: float,
                        sigma0: float,
                        beta: float,
                        volvol: float,
                        deltas: Optional[np.ndarray] = None,
                        is_remap_to_straddle_delta: bool = True,
                        is_analytic: bool = True,
                        ) -> pd.Series:
    if deltas is None:
        deltas = np.linspace(0.01, 0.99, 100)

    imp_strikes = infer_strikes_from_deltas(deltas=deltas,
                                            forward=forward,
                                            ttm=ttm,
                                            sigma0=sigma0,
                                            beta=beta,
                                            volvol=volvol)
    log_strikes = np.log(imp_strikes.to_numpy() / forward)
    pdfs = calc_logsv_pdf_core(ttm=ttm,
                               sigma0=sigma0,
                               beta=beta,
                               volvol=volvol,
                               log_strikes=log_strikes,
                               is_norm=False,
                               is_analytic=is_analytic)
    if is_remap_to_straddle_delta:
        vol_index = -2.0 * deltas + 1.0
    else:
        vol_index = deltas

    return pd.Series(pdfs, index=vol_index).sort_index()


def generate_grid_option_prices_from_slice(vols: pd.Series,
                                           given_log_strikes: np.ndarray,
                                           log_strike_grid: np.ndarray,
                                           p0_ref: float,
                                           ttm: float,
                                           vol_addon: Optional[float] = None
                                           ) -> Tuple[pd.Series, pd.Series]:
    """
    fit slice data and produce grid of option prices
    """
    fit_params = fit_logsv_ivols(log_strikes=given_log_strikes,
                                 mid_vols=vols.to_numpy(),
                                 ttm=ttm,
                                 is_vega_weights=True)

    if vol_addon is not None:
        fit_params[ATM_VOL] += vol_addon

    vols = calc_logsv_ivols(log_strikes=log_strike_grid, **fit_params)
    extended_strikes = p0_ref*np.exp(log_strike_grid)
    calls = bsm.compute_bsm_vanilla_slice_prices(ttm=ttm,
                                                 forward=p0_ref,
                                                 strikes=extended_strikes,
                                                 vols=vols,
                                                 optiontypes=np.full_like(extended_strikes, 'C', dtype=str))

    puts = bsm.compute_bsm_vanilla_slice_prices(ttm=ttm,
                                                forward=p0_ref,
                                                strikes=extended_strikes,
                                                vols=vols,
                                                optiontypes=np.full_like(extended_strikes, 'P', dtype=str))
    calls = pd.Series(calls, index=extended_strikes)
    puts = pd.Series(puts, index=extended_strikes)

    return puts, calls


class UnitTests(Enum):
    PDF = 1
    DELTAS = 2
    DELTA_CHECK = 3
    VOLS_IN_DELTA = 4
    PDFS_IN_DELTA = 5
    FIT = 6
    GENERATE_PRICES = 7


def run_unit_test(unit_test: UnitTests):

    # to get options data
    from option_chain_analytics.chain_loader_from_ts import create_chain_from_from_options_dfs
    from option_chain_analytics.chain_ts import OptionsDataDFs
    from option_chain_analytics.ts_loaders import ts_data_loader_wrapper

    if unit_test == UnitTests.PDF:
        log_strikes = np.linspace(-5, 5, 1000)
        ttms = np.linspace(0.1, 1.0, 10)

        pdfs = []
        for ttm in ttms:
            pdf = calc_logsv_pdf(ttm=ttm,
                                 sigma0=1.0,
                                 beta=1.0,
                                 volvol=1.0,
                                 log_strikes=log_strikes,
                                 is_norm=False)
            pdfs.append(pdf.rename(f"ttm={ttm:0.2f}"))
        pdfs = pd.concat(pdfs, axis=1)

        with sns.axes_style('darkgrid'):
            fig, ax = plt.subplots(1, 1, figsize=(10, 10), tight_layout=True)
        sns.lineplot(data=pdfs, dashes=False, ax=ax)

    elif unit_test == UnitTests.DELTAS:
        deltas = np.linspace(0.05, 0.95, 9)
        imp_strikes = infer_strikes_from_deltas(deltas=deltas,
                                                forward=1.0,
                                                ttm=1.0,
                                                sigma0=1.0,
                                                beta=-0.5,
                                                volvol=0.5)

        print(imp_strikes)

    elif unit_test == UnitTests.DELTA_CHECK:
        log_strikes = np.linspace(-3.0, 3.0, 100)
        vols = calc_logsv_ivols(log_strikes=log_strikes, sigma0=1.0, beta=0.5, volvol=0.5)
        bsm_deltas = bsm.compute_bsm_vanilla_slice_deltas(ttm=1.0,
                                                          forward=1.0,
                                                          strikes=np.exp(log_strikes),
                                                          vols=vols,
                                                          optiontypes=np.full_like(log_strikes, 'C', dtype=str))
        print(bsm_deltas)
        bsm_deltas = pd.Series(bsm_deltas, index=log_strikes)
        sns.lineplot(data=bsm_deltas)

    elif unit_test == UnitTests.VOLS_IN_DELTA:
        deltas = np.linspace(0.05, 0.95, 100)
        ttms = np.linspace(0.01, 1.0, 10)
        imp_vols = []
        for ttm in ttms:
            imp_vol = get_vols_delta_space(deltas=deltas,
                                           forward=1.0,
                                           ttm=ttm,
                                           sigma0=1.0,
                                           beta=0.0,
                                           volvol=0.5)
            imp_vols.append(imp_vol.rename(f"ttm={ttm: 0.2f}"))

        imp_vols = pd.concat(imp_vols, axis=1)
        sns.lineplot(data=imp_vols)

    elif unit_test == UnitTests.PDFS_IN_DELTA:
        deltas = np.linspace(0.05, 0.95, 100)
        ttms = np.linspace(0.01, 1.0, 10)
        pdfs = []
        for ttm in ttms:
            pdf = get_pdf_delta_space(deltas=deltas,
                                      forward=1.0,
                                      ttm=ttm,
                                      sigma0=1.0,
                                      beta=0.0,
                                      volvol=0.5,
                                      is_analytic=False)
            pdfs.append(pdf.rename(f"ttm={ttm: 0.2f}"))

        imp_vols = pd.concat(pdfs, axis=1)
        sns.lineplot(data=imp_vols)

    elif unit_test == UnitTests.FIT:
        from option_chain_analytics.ts_loaders import ts_data_loader_wrapper
        options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker='ETH'))
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")
        value_time = pd.Timestamp('2023-11-01 15:31:57.487172+00:00')
        chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=value_time)
        slice_id = '29Dec2023'
        this = chain.get_expiry_slice(slice_id=slice_id)
        vols, strikes = this.get_bid_mark_ask_vols()
        mid_vols = vols['ask_iv'].to_numpy()
        log_strikes = np.log(strikes.to_numpy()/this.forward)

        fit_params = fit_logsv_ivols(log_strikes=log_strikes, mid_vols=mid_vols, ttm=this.get_ttm(), is_vega_weights=True)
        print(fit_params)

    elif unit_test == UnitTests.GENERATE_PRICES:

        options_data_dfs = OptionsDataDFs(**ts_data_loader_wrapper(ticker='ETH'))
        time_index = options_data_dfs.get_timeindex()
        print(f"time_index={time_index}")
        value_time = pd.Timestamp('2023-11-01 15:31:57.487172+00:00')
        chain = create_chain_from_from_options_dfs(options_data_dfs=options_data_dfs, value_time=value_time)
        e_slice = chain.get_expiry_slice(slice_id='10Nov2023')
        p0_ref = 1800.0
        vols, given_log_strikes = e_slice.get_vols_with_logstrikes()
        vol = 0.4
        ttm = e_slice.get_ttm()
        log_strike_grid = np.linspace(-5.0*vol*np.sqrt(ttm), 0.5*vol*np.sqrt(ttm))

        generate_grid_option_prices_from_slice(vols=vols, given_log_strikes=given_log_strikes,
                                               log_strike_grid=log_strike_grid,
                                               p0_ref=p0_ref,
                                               ttm=ttm)

    plt.show()


if __name__ == '__main__':

    unit_test = UnitTests.FIT

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
