import pandas as pd

from option_chain_analytics import OptionsDataDFs, create_chain_at_time, create_chain_timeseries
from option_chain_analytics.data.deribit import load_local_deribit_contract_ts_data
from option_chain_analytics.option_chain import SliceColumn, UnderlyingColumn


def test_chain_creation_uses_weighted_forward_with_current_qis() -> None:
    value_time = pd.Timestamp('2024-01-02 08:00:00', tz='UTC')
    expiry = pd.Timestamp('2024-01-26 08:00:00', tz='UTC')
    chain_ts = pd.DataFrame(
        {
            SliceColumn.CONTRACT.value: ['BTC-C', 'BTC-P'],
            SliceColumn.EXCHANGE_TIME.value: [value_time, value_time],
            SliceColumn.MATURITY_ID.value: ['26JAN2024', '26JAN2024'],
            SliceColumn.EXPIRY.value: [expiry, expiry],
            SliceColumn.TTM.value: [24.0 / 365.0, 24.0 / 365.0],
            SliceColumn.OPTION_TYPE.value: ['C', 'P'],
            SliceColumn.STRIKE.value: [100.0, 100.0],
            SliceColumn.FORWARD_PRICE.value: [100.0, 110.0],
            SliceColumn.OPEN_INTEREST.value: [1.0, 3.0],
        }
    )
    options = OptionsDataDFs(chain_ts=chain_ts, spot_data=pd.DataFrame(), ticker='BTC')

    chain = create_chain_at_time(options_data=options, value_time=value_time)

    assert chain.undelying_df.loc['26JAN2024', UnderlyingColumn.FORWARD_PRICE] == 107.5


def test_deribit_loader_adds_forward_price_for_chain_creation(monkeypatch) -> None:
    chain_ts = pd.DataFrame({'underlying_price': [100.0]})
    spot_data = pd.DataFrame({'close': [100.0]})

    def fake_load_df_from_feather(**kwargs) -> pd.DataFrame:
        if 'file_name' in kwargs:
            return spot_data.copy()
        return chain_ts.copy()

    monkeypatch.setattr('option_chain_analytics.data.deribit.qis.load_df_from_feather', fake_load_df_from_feather)

    loaded = load_local_deribit_contract_ts_data(ticker='BTC', local_path='unused')

    assert loaded['chain_ts'][SliceColumn.FORWARD_PRICE.value].iloc[0] == 100.0


def test_chain_creation_can_select_only_the_previous_observation() -> None:
    first_time = pd.Timestamp('2024-01-02 08:00:00', tz='UTC')
    second_time = pd.Timestamp('2024-01-03 08:00:00', tz='UTC')
    requested_time = pd.Timestamp('2024-01-02 16:00:00', tz='UTC')
    expiry = pd.Timestamp('2024-01-26 08:00:00', tz='UTC')
    chain_ts = pd.DataFrame(
        {
            SliceColumn.CONTRACT.value: ['BTC-C-1', 'BTC-P-1', 'BTC-C-2', 'BTC-P-2'],
            SliceColumn.EXCHANGE_TIME.value: [
                first_time,
                first_time,
                second_time,
                second_time,
            ],
            SliceColumn.MATURITY_ID.value: ['26JAN2024'] * 4,
            SliceColumn.EXPIRY.value: [expiry] * 4,
            SliceColumn.TTM.value: [24.0 / 365.0, 24.0 / 365.0, 23.0 / 365.0, 23.0 / 365.0],
            SliceColumn.OPTION_TYPE.value: ['C', 'P', 'C', 'P'],
            SliceColumn.STRIKE.value: [100.0] * 4,
            SliceColumn.FORWARD_PRICE.value: [100.0, 100.0, 101.0, 101.0],
            SliceColumn.OPEN_INTEREST.value: [1.0] * 4,
        }
    )
    options = OptionsDataDFs(chain_ts=chain_ts, spot_data=pd.DataFrame(), ticker='BTC')

    exact = create_chain_at_time(
        options_data=options,
        value_time=requested_time,
    )
    previous = create_chain_at_time(
        options_data=options,
        value_time=requested_time,
        time_selection='previous',
    )
    before_history = create_chain_at_time(
        options_data=options,
        value_time=first_time - pd.Timedelta(seconds=1),
        time_selection='previous',
    )
    scheduled = create_chain_timeseries(
        options_data=options,
        dates_schedule=pd.DatetimeIndex([requested_time]),
    )

    assert exact is None
    assert previous is not None
    assert previous.value_time == first_time
    assert previous.options_df[SliceColumn.EXCHANGE_TIME.value].eq(first_time).all()
    assert before_history is None
    assert scheduled[requested_time].value_time == first_time
