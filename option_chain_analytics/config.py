"""
define api and data specific conversions of options and futures tickers
"""
import pandas as pd
from typing import Optional
from enum import Enum


TIME_FMT = '%Y%m%d%H%M%S'
EXPIRY_DATE_FORMAT = '%d%b%Y'
SECONDS_PER_DAY = 24*60*60  # hours, minute, seconds


class NearestStrikeOnGrid(Enum):
    """
    for selection of strikes
    this specifies nearest strike from the strikes grid, for put ratios must be strictly below or above
    """
    NEAREST = 0
    MAX_OI = 1
    ABOVE = 2
    BELOW = 3


class StrikeSelection(Enum):
    # strike selection for a strategy
    ATM = 1
    DELTA = 2


def compute_time_to_maturity(maturity_time: pd.Timestamp,
                             value_time: pd.Timestamp,
                             is_floor_at_zero: bool = True,
                             af: float = 365
                             ) -> float:
    """
    return annualised difference between mat_date and value_time
    """
    ttm = (maturity_time - value_time).total_seconds() / (af*SECONDS_PER_DAY)
    if is_floor_at_zero and ttm < 0.0:
        ttm = 0.0
    return ttm


def compute_days_to_maturity(maturity_time: pd.Timestamp,
                             value_time: pd.Timestamp,
                             is_floor_at_zero: bool = True,
                             af: float = 365
                             ) -> float:
    """
    return annualised difference between mat_date and value_time
    """
    ttm = (maturity_time - value_time).total_seconds() / (af*SECONDS_PER_DAY)
    if is_floor_at_zero and ttm < 0.0:
        ttm = 0.0
    return ttm


def mat_to_timestamp(mat: str,
                     date_format: Optional[str] = None,  # deribit = "%d%b%y"
                     hour_offset: Optional[int] = 8
                     ) -> pd.Timestamp:
    """
    from maturity string get timestamp
    """
    mat = pd.Timestamp(pd.to_datetime(mat, format=date_format), tz='UTC')
    if hour_offset is not None:
        mat = mat + pd.to_timedelta(hour_offset, unit='h')
    return mat


def get_file_name(ticker: str, freq: Optional[str], hour_offset: Optional[int]) -> str:
    if freq is not None:
        if freq in ['h', 'H']:
            file_name = f"{ticker}_freq_{freq}"
        else:
            if hour_offset is not None:
                file_name = f"{ticker}_freq_{freq}_hour_{hour_offset}"
            else:
                file_name = f"{ticker}_freq_{freq}"
    else:
        file_name = ticker
    return file_name
