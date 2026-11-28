"""Exercise the historical and expanded Bloomberg snapshot formats offline."""

import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def test_bloomberg_grid_tenors_and_forward_ticker(tmp_path):
    example = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "fx_smile_bloomberg.py"))
    tenors = ("1M", "2M", "3M", "6M", "1Y")
    rows = {"EURUSD Curncy": {"px_mid": 1.2, "maturity": "2025-02-05"}, "SOFRRATE Index": {"px_last": 3.0}}
    for tenor, months in zip(tenors, (1, 2, 3, 6, 12)):
        expiry = pd.Timestamp("2025-02-03") + pd.DateOffset(months=months)
        for kind, mid in (("V", 8.0), ("10R", -0.3), ("25R", -0.2), ("10B", 0.7), ("25B", 0.2)):
            rows[f"EURUSD{kind}{tenor} Curncy"] = {"opt_expire_dt": expiry.date(), "px_mid": mid}
        rows[f"EURUSD{months}M Curncy"] = {"maturity": (expiry + pd.Timedelta(days=2)).date(),
                                          "px_mid": 10.0*months, "fwd_scale": 4.0}
    raw = pd.DataFrame.from_dict(rows, orient="index").assign(retrieved_at_utc="2025-02-03T09:00:00Z")
    assert set(example["_securities"](example["TENORS"])) == set(raw.index)
    path = tmp_path / "private.csv"
    raw.to_csv(path, index_label="security")
    panel = example["reconstruct"](path).chain_ts
    assert panel.groupby("fx_tenor", sort=False).size().to_dict() == dict.fromkeys(tenors, 5)
    np.testing.assert_allclose(panel.loc[panel.fx_tenor == "1Y", "forward_price"], 1.212)

    raw.loc[raw.index[:14]].to_csv(path, index_label="security")
    old = example["reconstruct"](path).chain_ts
    pd.testing.assert_frame_equal(old.reset_index(drop=True), panel.iloc[:10].reset_index(drop=True))

    raw.drop(index="EURUSD10B3M Curncy").to_csv(path, index_label="security")
    with pytest.raises(ValueError, match="3M"):
        example["reconstruct"](path)
