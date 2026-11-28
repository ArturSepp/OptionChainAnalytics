"""Independent Black round trips for OCA's two broker strangles and four delta conventions."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq
from scipy.special import ndtr

from option_chain_analytics import FXSmileQuote, create_chain_at_time, fx_smile_to_options_data


def quote(**changes):
    base = FXSmileQuote(
        pair="EURUSD",
        value_time=pd.Timestamp("2025-01-02 15:00Z"),
        expiry=pd.Timestamp("2025-07-02 14:00Z"),
        forward=1.12,
        spot=1.10,
        discount=0.973,
        atm=0.13,
        rr10=-0.031,
        rr25=-0.016,
        ms10=0.014,
        ms25=0.005,
        delta_convention="spot",
        atm_convention="delta_neutral",
        source="synthetic broker mids",
    )
    return replace(base, **changes)


@pytest.mark.parametrize("convention", ["forward", "spot", "forward_pa", "spot_pa"])
@pytest.mark.parametrize("atm", ["spot", "forward", "delta_neutral"])
def test_fx_wings_round_trip_in_observed_quote_units(convention, atm):
    q = quote(delta_convention=convention, atm_convention=atm)
    panel = fx_smile_to_options_data([q])
    df = panel.chain_ts.set_index("fx_pillar")
    t = (q.expiry - q.value_time).total_seconds() / (365 * 86400)

    def normalized_delta(k, v, sign):
        st = v * np.sqrt(t)
        d1 = np.log(q.forward / k) / st + st / 2
        if convention.endswith("_pa"):
            d = sign * k / q.forward * ndtr(sign * (d1 - st))
        else:
            d = sign * ndtr(sign * d1)
        return d * (q.discount * q.forward / q.spot if convention.startswith("spot") else 1.0)

    def price(k, v, sign):
        st = v * np.sqrt(t)
        d1 = np.log(q.forward / k) / st + st / 2
        return sign * q.discount * (q.forward * ndtr(sign * d1) - k * ndtr(sign * (d1 - st)))

    atm_k = df.at["ATM", "strike"]
    if atm == "delta_neutral":
        assert normalized_delta(atm_k, q.atm, 1) + normalized_delta(atm_k, q.atm, -1) == pytest.approx(0, abs=1e-12)
    else:
        assert atm_k == (q.spot if atm == "spot" else q.forward)
    assert df.at["ATM", "mark_iv"] == q.atm
    for level, rr, ms in [(10, q.rr10, q.ms10), (25, q.rr25, q.ms25)]:
        wings = df.loc[[f"{level}P", f"{level}C"]]
        assert wings.mark_iv.iloc[1] - wings.mark_iv.iloc[0] == pytest.approx(rr, abs=1e-12)
        strikes = []
        for sign, row in zip((-1, 1), wings.itertuples()):
            assert normalized_delta(row.strike, row.mark_iv, sign) == pytest.approx(sign * level / 100, abs=2e-10)
            assert row.fx_quote_delta == pytest.approx(sign * level / 100, abs=2e-10)
            # Independently locate the market strangle strikes using its single quoted IV.
            bracket = (0.25 * q.forward, q.forward) if sign < 0 else (q.forward, 4 * q.forward)
            k = brentq(lambda x: normalized_delta(x, q.atm + ms, sign) - sign * level / 100, *bracket)
            assert row.market_strangle_strike == pytest.approx(k, abs=2e-10)
            strikes.append(k)
        iv = np.interp(np.log(strikes), np.log(df.strike), df.mark_iv)
        premium = price(strikes[0], iv[0], -1) + price(strikes[1], iv[1], 1)
        common_vol = brentq(lambda v: price(strikes[0], v, -1) + price(strikes[1], v, 1) - premium, 0.001, 1.0)
        assert common_vol - q.atm == pytest.approx(ms, abs=2e-10)
    assert list(df.index) == ["10P", "25P", "ATM", "25C", "10C"]
    assert df[["bid_iv", "ask_iv", "bid_price", "ask_price", "open_interest"]].isna().all().all()
    assert df.quote_origin.eq("derived_fx_smile_mid").all()
    chain = create_chain_at_time(panel, q.value_time)
    assert len(chain.options_df) == 5
    assert chain.undelying_df.iloc[0]["spot_price"] == q.spot
    assert chain.undelying_df.iloc[0]["forward_price"] == pytest.approx(q.forward)


def test_fx_history_and_invalid_quotes():
    q = quote(rr10=0, rr25=0, ms10=0, ms25=0)
    q2 = replace(q, value_time=q.value_time + pd.Timedelta(days=1), atm=0.14)
    panel = fx_smile_to_options_data([q, q2])
    sliced = create_chain_at_time(panel, q2.value_time - pd.Timedelta(seconds=1), time_selection="previous")
    np.testing.assert_allclose(sliced.options_df.mark_iv, q.atm, rtol=0, atol=1e-12)
    for invalid in [
        dict(rr10=np.nan),
        dict(ms10=-1),
        dict(delta_convention="unknown"),
        dict(expiry=q.value_time),
        dict(value_time=q.value_time.tz_localize(None)),
    ]:
        with pytest.raises(ValueError):
            fx_smile_to_options_data([replace(q, **invalid)])
    with pytest.raises(ValueError, match="duplicate"):
        fx_smile_to_options_data([q, q])
