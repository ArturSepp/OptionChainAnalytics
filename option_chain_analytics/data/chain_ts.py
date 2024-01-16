"""
collector of aligned time series data for option
options data is split in frames
"""
from __future__ import annotations

# package
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Literal, List, Union, Optional
from enum import Enum
import qis
from qis import TimePeriod

# analytics
from option_chain_analytics.option_chain import SliceColumn
from option_chain_analytics.data.config import get_ttm_from_future_ticker, FutureTickerConfig


@dataclass
class ChainTs:
    """
    df collection for options and futures time series
    chain_ts must contain SliceColumn.EXCHANGE_TIME.value
    the most frequent request will be get df[contracts] at given timestamp
    to expedite request we add groupby[SliceColumn.EXCHANGE_TIME.value]
    """
    chain_ts: pd.DataFrame
    spot_data: pd.DataFrame
    ticker: str

    def __post_init__(self):
        self.chain_ts_group_by_time = self.chain_ts.groupby(SliceColumn.EXCHANGE_TIME.value)
        self.ewm_vol: Optional[pd.Series] = None

    def get_contract_data(self, contact: str) -> pd.DataFrame:
        df = self.chain_ts.loc[self.chain_ts[SliceColumn.CONTRACT.value] == contact, :]
        return df

    def print(self):
        print('chain_ts')
        print(self.chain_ts)
        print('spot_data')
        print(self.spot_data)

    def get_timeindex(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.chain_ts_group_by_time.groups.keys())

    def get_start_end_date(self) -> TimePeriod:
        times = self.get_timeindex()
        return qis.TimePeriod(times.min(), times.max())

    def get_spot_data(self, time_period: TimePeriod = None) -> pd.DataFrame:
        df = self.spot_data
        if time_period is not None:
            df = time_period.locate(df)
        return df

    def get_time_slice(self,
                       timestamp: pd.Timestamp,
                       contracts: List[str] = None
                       ) -> pd.DataFrame:
        """
         get non-nan time slice from series
         return is df(index=contracts, colums=[mark_rpice, mark_vol,...])
         """
        if timestamp in self.chain_ts_group_by_time.groups:
            df = self.chain_ts_group_by_time.get_group(timestamp)
            df = df.set_index(SliceColumn.CONTRACT.value, drop=False)
            df.index.name = 'contract'

            # remove dublicates per timestamp
            df = df.loc[~df.index.duplicated(keep='first')]

            if contracts is not None:
                df = df.iloc[np.in1d(df.index, contracts, assume_unique=False), :]
        else:
            # print(f"no slice data for {timestamp}")
            df = pd.DataFrame()
        return df

    def get_spot_price(self,
                       value_time: pd.Timestamp = None,
                       index: Union[pd.DatetimeIndex, pd.Index] = None
                       ) -> Union[float, pd.Series]:
        value = self.spot_data['close'].rename(self.ticker)
        if value_time is not None:
            if value_time in value.index:
                value = value[value_time]
            else:
                raise KeyError(f"in get_spot_price {value_time} not in {value.index}")
        elif index is not None:
            value = value.reindex(index=index, method='ffill').fillna(method='ffill')
        return value

    def get_funding_rate(self,
                         freq: Optional[Literal['H', 'D']] = 'H',
                         index: Union[pd.DatetimeIndex, pd.Index] = None,
                         is_rescale_to_one_hour: bool = True,
                         time_period: TimePeriod = None
                         ) -> pd.Series:
        """
        deribit reports hourly funding rate extrapolated to 8h interval
        for h freq we resample at 8h and return last
        for d freq we resample at 8h and then return the sum
        if freq is Non we return actual rate, it needs to be divided by 8 for comps H or D frequences with is_rescale_to_one_hour = True
        """
        funding_rate_1h = self.spot_data['funding_rate'].rename(self.ticker)
        if freq is not None:
            funding_rate_8h = funding_rate_1h.resample('8h').mean()
            if freq == 'H':
                funding_rate = funding_rate_8h
                if index is not None:
                    funding_rate = funding_rate.reindex(index=index).fillna(0.0)
            elif freq == 'D':
                funding_rate = funding_rate_8h.resample('D').sum()
                if index is not None:
                    funding_rate = funding_rate.reindex(index=index, method='ffill').fillna(0.0)
            else:
                raise NotImplementedError(f"freq={freq}")
        else:
            # funding_rate = funding_rate_1h.cumsum(0).reindex(index=index, method='ffill').diff(1)
            funding_rate = funding_rate_1h
            if is_rescale_to_one_hour:
                funding_rate = funding_rate / 8.0  # deribit computes funding based on 8h frequency

        if time_period is not None:
            funding_rate = time_period.locate(funding_rate)

        return funding_rate

    def get_ewm_vol(self,
                    value_time: pd.Timestamp,
                    span: float = 168  # =7*24
                    ) -> float:
        if self.ewm_vol is None:
            returns = np.log(self.spot_data['close']).diff()
            self.ewm_vol = qis.compute_ewm_vol(data=returns, span=span, af=24.0 * 365.0)
        idx = self.ewm_vol.index.get_indexer([value_time], method='ffill')
        vol = self.ewm_vol.iloc[idx].to_numpy()[0]
        return vol

    @classmethod
    def reduce(cls, obj: ChainTs, contracts: List[str]) -> ChainTs:
        """
        reduce chain to contain only given contracts
        """
        chain_ts = obj.chain_ts
        return ChainTs(chain_ts=chain_ts.loc[chain_ts[SliceColumn.CONTRACT.value].isin(contracts), :],
                       spot_data=obj.spot_data,
                       ticker=obj.ticker)


@dataclass
class FuturesChainTs(ChainTs):
    """
    implementation of options time series data
    """

    future_ticker_config: FutureTickerConfig = field(default=FutureTickerConfig.CMS, init=True)

    class FuturesDataColumns(str, Enum):
        MARK_PRICE = 'mark_price'
        OPEN = 'open'
        HIGH = 'high'
        LOW = 'low'
        CLOSE = 'close'
        VOLUME = 'usd_volume'
        VOLUME_CONTRACTS = 'contract_count'
        OI_VOLUME = 'oi_value_usd'
        OI_CONTRACTS = 'oi_contract_count'

    def get_term_structure(self,
                           value_time: pd.Timestamp,
                           data: str = 'mark_price'
                           ) -> pd.DataFrame:

        contracts_data = self.get_contracts_data(value_time=value_time, data=data).dropna().rename(data).to_frame()
        ttms = [get_ttm_from_future_ticker(value_time=value_time, contract=x) for x in contracts_data.index]
        contracts_data['ttms'] = ttms
        return contracts_data


@dataclass
class OptionsDataDFs(ChainTs):
    """
    implementation of options time series data
    fields of SliceColumn are contained in data_dict
    """
    # do not pass to ChainTs
    # todo: do you need it here if all info (maturity, option type, etc is passed inside option data dfs)
    #option_ticker_config: OptionTickerConfig = field(default=OptionTickerConfig.DERIBIT, init=True)

    @classmethod
    def reduce(cls, obj: OptionsDataDFs, contracts: List[str]) -> OptionsDataDFs:
        """
        reduce chain to contain only given contracts
        """
        chain_ts = obj.chain_ts
        return OptionsDataDFs(chain_ts=chain_ts.loc[chain_ts[SliceColumn.CONTRACT.value].isin(contracts), :],
                              spot_data=obj.spot_data,
                              ticker=obj.ticker)
                              #option_ticker_config=obj.option_ticker_config)


class UnitTests(Enum):
    TEST_CHAIN = 1


def run_unit_test(unit_test: UnitTests):

    from option_chain_analytics import local_path as local_path

    if unit_test == UnitTests.TEST_CHAIN:
        ticker = 'ETH'
        chain_ts = qis.load_df_from_feather(file_name=f"{ticker}_freq_H",
                                            index_col=None,
                                            local_path=f"{local_path.get_resource_path()}\\tardis\\")
        spot_data = qis.load_df_from_feather(file_name=f"{ticker}-spot",
                                             local_path=f"{local_path.get_resource_path()}\\deribit\\")

        chain_ts = ChainTs(chain_ts=chain_ts, spot_data=spot_data, ticker=ticker)
        chain_ts.print()
        chain_ts.get_start_end_date().print()

        df = chain_ts.get_time_slice(timestamp=pd.Timestamp('2019-04-01 08:00:00+00:00'))
        print(df)


if __name__ == '__main__':

    unit_test = UnitTests.TEST_CHAIN

    is_run_all_tests = False
    if is_run_all_tests:
        for unit_test in UnitTests:
            run_unit_test(unit_test=unit_test)
    else:
        run_unit_test(unit_test=unit_test)
