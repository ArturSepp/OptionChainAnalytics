import pandas as pd

from option_chain_analytics.chain_loader_from_ts import create_chain_from_from_options_dfs
from option_chain_analytics.chain_ts import OptionsDataDFs
from option_chain_analytics.option_chain import SliceColumn, UnderlyingColumn
from option_chain_analytics.ts_loaders import load_local_deribit_contract_ts_data


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

    chain = create_chain_from_from_options_dfs(options_data_dfs=options, value_time=value_time)

    assert chain.undelying_df.loc['26JAN2024', UnderlyingColumn.FORWARD_PRICE] == 107.5


def test_deribit_loader_adds_forward_price_for_chain_creation(monkeypatch) -> None:
    chain_ts = pd.DataFrame({'underlying_price': [100.0]})
    spot_data = pd.DataFrame({'close': [100.0]})

    def fake_load_df_from_feather(**kwargs) -> pd.DataFrame:
        if 'file_name' in kwargs:
            return spot_data.copy()
        return chain_ts.copy()

    monkeypatch.setattr('option_chain_analytics.ts_loaders.qis.load_df_from_feather', fake_load_df_from_feather)

    loaded = load_local_deribit_contract_ts_data(ticker='BTC', local_path='unused')

    assert loaded['chain_ts'][SliceColumn.FORWARD_PRICE.value].iloc[0] == 100.0
