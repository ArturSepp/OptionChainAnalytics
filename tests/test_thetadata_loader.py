from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
import vanilla_option_pricers as bsm

from option_chain_analytics import (
    DataSource,
    OptionsDataDFs,
    SliceColumn,
    create_chain_at_time,
    load_thetadata_eod_options_timeseries,
    map_thetadata_eod_options_data,
    ts_data_loader_wrapper,
)

VALUE_DATE = date(2026, 8, 17)
EXPIRATION = date(2026, 9, 18)
OPTION_REPORT_TIME = pd.Timestamp('2026-08-17 17:15:00', tz='America/New_York')
SPOT_REPORT_TIME = pd.Timestamp('2026-08-17 17:10:00', tz='America/New_York')
EXPIRY_TIME = pd.Timestamp('2026-09-18 16:00:00', tz='America/New_York')
FORWARD = 102.0
DISCOUNT = 0.995
VOLATILITY = 0.25


def _option_source() -> pd.DataFrame:
    ttm = (EXPIRY_TIME - OPTION_REPORT_TIME).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
    rows = []
    for strike in (95.0, 100.0, 105.0):
        for right, option_type in (('CALL', 'C'), ('PUT', 'P')):
            mark = bsm.compute_bsm_vanilla_price(
                ttm=ttm,
                forward=FORWARD,
                strike=strike,
                optiontype=option_type,
                vol=VOLATILITY,
                discfactor=DISCOUNT,
            )
            rows.append(
                {
                    'symbol': 'DEMO',
                    'expiration': EXPIRATION,
                    'strike': strike,
                    'right': right,
                    'created': OPTION_REPORT_TIME,
                    'volume': 10,
                    'bid_size': 5,
                    'bid': mark - 0.01,
                    'ask_size': 6,
                    'ask': mark + 0.01,
                }
            )
    return pd.DataFrame(rows)


def _spot_source(report_time: pd.Timestamp = SPOT_REPORT_TIME) -> pd.DataFrame:
    return pd.DataFrame({'created': [report_time], 'close': [100.0]})


def _rate_source() -> pd.DataFrame:
    ttm = (EXPIRY_TIME - OPTION_REPORT_TIME).total_seconds() / (365.0 * 24.0 * 60.0 * 60.0)
    rate_percent = -100.0 * np.log(DISCOUNT) / ttm
    return pd.DataFrame({'created': [VALUE_DATE], 'rate': [rate_percent]})


@dataclass
class FakeThetaDataClient:
    option_source: pd.DataFrame
    spot_source: pd.DataFrame

    def option_list_expirations(self, symbol: str) -> pd.DataFrame:
        assert symbol == 'DEMO'
        return pd.DataFrame({'expiration': [EXPIRATION]})

    def option_history_eod(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        expiration: date,
    ) -> pd.DataFrame:
        assert start_date == end_date == VALUE_DATE
        assert symbol == 'DEMO'
        assert expiration == EXPIRATION
        return self.option_source.copy()

    def stock_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        assert symbol == 'DEMO'
        assert start_date == end_date == VALUE_DATE
        return self.spot_source.copy()

    def interest_rate_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        assert symbol == 'SOFR'
        assert start_date == VALUE_DATE - timedelta(days=7)
        assert end_date == VALUE_DATE
        return _rate_source()


def test_thetadata_mapper_produces_complete_reconstructable_chain() -> None:
    mapped = map_thetadata_eod_options_data(
        option_source=_option_source(),
        spot_source=_spot_source(),
        ticker='DEMO',
    )
    chain_ts = mapped['chain_ts']

    assert list(chain_ts.columns) == [column.value for column in SliceColumn]
    assert len(chain_ts) == 6
    assert str(chain_ts[SliceColumn.EXCHANGE_TIME.value].dt.tz) == 'UTC'
    assert str(chain_ts[SliceColumn.EXPIRY.value].dt.tz) == 'UTC'
    assert chain_ts[SliceColumn.SPOT_PRICE.value].eq(100.0).all()
    assert np.allclose(chain_ts[SliceColumn.FORWARD_PRICE.value], FORWARD)
    assert np.allclose(chain_ts[SliceColumn.DISCOUNT.value], DISCOUNT)
    assert np.isfinite(chain_ts[SliceColumn.MARK_IV.value]).all()
    assert chain_ts[SliceColumn.BID_IV.value].le(chain_ts[SliceColumn.MARK_IV.value]).all()
    assert chain_ts[SliceColumn.MARK_IV.value].le(chain_ts[SliceColumn.ASK_IV.value]).all()
    assert np.isfinite(
        chain_ts[
            [
                SliceColumn.DELTA.value,
                SliceColumn.VEGA.value,
                SliceColumn.THETA.value,
                SliceColumn.GAMMA.value,
            ]
        ].to_numpy()
    ).all()

    options_data = OptionsDataDFs(**mapped)
    value_time = options_data.get_timeindex()[0]
    chain = create_chain_at_time(options_data=options_data, value_time=value_time)
    assert chain is not None
    assert len(chain.expiry_slices) == 1
    assert len(chain.options_df) == 6


def test_thetadata_implied_vols_reprice_observed_marks() -> None:
    chain_ts = map_thetadata_eod_options_data(
        option_source=_option_source(),
        spot_source=_spot_source(),
        ticker='DEMO',
    )['chain_ts']

    repriced = [
        bsm.compute_bsm_vanilla_price(
            ttm=float(row[SliceColumn.TTM.value]),
            forward=float(row[SliceColumn.FORWARD_PRICE.value]),
            strike=float(row[SliceColumn.STRIKE.value]),
            optiontype=str(row[SliceColumn.OPTION_TYPE.value]),
            vol=float(row[SliceColumn.MARK_IV.value]),
            discfactor=float(row[SliceColumn.DISCOUNT.value]),
        )
        for _, row in chain_ts.iterrows()
    ]
    assert np.allclose(repriced, chain_ts[SliceColumn.MARK_PRICE.value], rtol=1e-7, atol=1e-9)


def test_thetadata_rate_report_anchors_discount_and_parity_forward() -> None:
    chain_ts = map_thetadata_eod_options_data(
        option_source=_option_source(),
        spot_source=_spot_source(),
        rate_source=_rate_source(),
        ticker='DEMO',
    )['chain_ts']

    assert np.allclose(chain_ts[SliceColumn.DISCOUNT.value], DISCOUNT)
    assert np.allclose(chain_ts[SliceColumn.FORWARD_PRICE.value], FORWARD)
    assert chain_ts.attrs['discount_convention'].startswith('flat continuously compounded')


def test_thetadata_spot_alignment_never_uses_a_future_report() -> None:
    later_spot_time = OPTION_REPORT_TIME + pd.Timedelta(minutes=1)
    mapped = map_thetadata_eod_options_data(
        option_source=_option_source(),
        spot_source=_spot_source(report_time=later_spot_time),
        ticker='DEMO',
    )

    assert mapped['chain_ts'][SliceColumn.SPOT_PRICE.value].isna().all()
    assert mapped['spot_data'].index[0] > mapped['chain_ts'][SliceColumn.EXCHANGE_TIME.value].max()


def test_thetadata_loader_routes_through_public_data_source() -> None:
    client = FakeThetaDataClient(_option_source(), _spot_source())
    mapped = ts_data_loader_wrapper(
        data_source=DataSource.THETADATA_EOD,
        ticker='DEMO',
        value_date=VALUE_DATE,
        client=client,
    )

    assert mapped['ticker'] == 'DEMO'
    assert len(mapped['chain_ts']) == 6
    assert mapped['chain_ts'].attrs['source'] == 'thetadata_option_eod'


@dataclass
class FakeThetaDataHistoryClient:
    def option_history_eod(
        self,
        start_date: date,
        end_date: date,
        symbol: str,
        expiration: date,
        strike_range: int | None = None,
    ) -> pd.DataFrame:
        assert symbol == 'DEMO'
        assert expiration == EXPIRATION
        assert strike_range == 20
        frames = []
        for report_date in pd.bdate_range(start_date, end_date):
            frame = _option_source()
            frame['created'] = pd.Timestamp(report_date.date()).tz_localize(
                'America/New_York'
            ) + pd.Timedelta(hours=17, minutes=15)
            frames.append(frame)
        return pd.concat(frames, ignore_index=True)

    def stock_history_eod(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        assert symbol == 'DEMO'
        rows = [
            {
                'created': pd.Timestamp(report_date.date()).tz_localize(
                    'America/New_York'
                ) + pd.Timedelta(hours=17, minutes=10),
                'close': 100.0,
            }
            for report_date in pd.bdate_range(start_date, end_date)
        ]
        return pd.DataFrame(rows)


def test_thetadata_timeseries_loader_returns_exact_point_in_time_panel() -> None:
    mapped = load_thetadata_eod_options_timeseries(
        ticker='demo',
        start_date='2026-08-17',
        end_date='2026-08-18',
        expirations=[EXPIRATION],
        min_dte=0,
        max_dte=60,
        client=FakeThetaDataHistoryClient(),
    )
    options_data = OptionsDataDFs(**mapped)

    assert options_data.ticker == 'DEMO'
    assert len(options_data.get_timeindex()) == 2
    assert options_data.get_timeindex()[0] == pd.Timestamp('2026-08-17 21:15:00+00:00')
    assert options_data.spot_data.index[0] < options_data.get_timeindex()[0]
    assert mapped['chain_ts'][SliceColumn.CONTRACT_SIZE.value].eq(100.0).all()
