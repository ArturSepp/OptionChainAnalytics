from __future__ import annotations

import runpy
from datetime import date

import matplotlib.pyplot as plt
import pandas as pd
import pytest


class FakeThetaDataHistoryClient:
    expiration = date(2026, 9, 18)

    def __init__(self, offline_client_type: type) -> None:
        self.offline_client_type = offline_client_type

    def option_history_eod(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        expiration: date,
        strike_range: int | None = None,
    ) -> pd.DataFrame:
        assert strike_range == 20
        return pd.concat(
            [
                self.offline_client_type(value_date.date(), expiration).option_history_eod(
                    start_date=value_date.date(),
                    end_date=value_date.date(),
                    symbol=symbol,
                    expiration=expiration,
                )
                for value_date in pd.bdate_range(start_date, end_date)
            ],
            ignore_index=True,
        )

    def stock_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        return pd.concat(
            [
                self.offline_client_type(value_date.date(), self.expiration).stock_history_eod(
                    symbol=symbol,
                    start_date=value_date.date(),
                    end_date=value_date.date(),
                )
                for value_date in pd.bdate_range(start_date, end_date)
            ],
            ignore_index=True,
        )


def test_thetadata_timeseries_example_builds_oca_history_and_plot(tmp_path) -> None:
    single_date_example = runpy.run_path('examples/fetch_thetadata_eod.py')
    timeseries_example = runpy.run_path('examples/fetch_thetadata_atm_timeseries.py')
    client = FakeThetaDataHistoryClient(single_date_example['OfflineThetaDataClient'])
    output_path = tmp_path / 'atm_vol.png'

    options_data, chains, atm_data, figure = timeseries_example['fetch_and_plot_thetadata_atm_vols'](
        ticker='aapl',
        start_date='2026-08-17',
        end_date='2026-08-18',
        expirations=[client.expiration],
        min_dte=7,
        max_dte=60,
        output_path=output_path,
        client=client,
    )

    assert options_data.ticker == 'AAPL'
    assert len(options_data.get_timeindex()) == 2
    assert len(chains) == 2
    assert list(atm_data.columns) == ['atm_vol', 'skew', 'expiration', 'dte']
    assert atm_data['atm_vol'].to_numpy() == pytest.approx([0.25, 0.25])
    assert atm_data['skew'].to_numpy() == pytest.approx([0.0, 0.0], abs=1e-12)
    assert atm_data['expiration'].nunique() == 1
    assert output_path.stat().st_size > 0
    plt.close(figure)

    skew_figure = timeseries_example['plot_skew'](atm_data=atm_data, ticker='AAPL', delta=0.25)
    skew_output_path = tmp_path / 'skew.png'
    skew_figure.savefig(skew_output_path)
    assert skew_output_path.stat().st_size > 0
    plt.close(skew_figure)
