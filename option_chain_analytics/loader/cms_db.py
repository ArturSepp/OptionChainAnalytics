import os
import pandas as pd
from tqdm import tqdm
from typing import Dict, Optional, Union
from enum import Enum

import qis
from qis.sql_engine import get_engine

import option_chain_analytics.data.config as gu
from option_chain_analytics.option_chain import SliceColumn

# will serve as columns for value data

CMS_SLICE_COLUMNS = [SliceColumn.CONTRACT,
                     SliceColumn.MARK_PRICE,
                     SliceColumn.UNDERLYING_PRICE,
                     SliceColumn.BID_PRICE,
                     SliceColumn.ASK_PRICE,
                     SliceColumn.MARK_IV,
                     SliceColumn.BID_IV,
                     SliceColumn.ASK_IV,
                     SliceColumn.OPEN_INTEREST,
                     SliceColumn.DELTA,
                     SliceColumn.VEGA,
                     SliceColumn.THETA,
                     SliceColumn.GAMMA,
                     SliceColumn.EXCHANGE_TIME,
                     SliceColumn.USD_MULTIPLIER] # inserted as column
