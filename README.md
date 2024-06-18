# OptionChainAnalytics
 Analytics for processing option chain and options time series data


Core python dependencies:

    python = ">=3.8,<3.11"
    numba = ">=0.59.0"
    numpy = ">=1.26.4"

Core packages dependencies

    vanilla_option_pricers = ">=1.0.1"
    qis = ">=2.0.68"



<strong>OptionChainAnalytics: Option Chain Analytics</strong>

Module option_chain_analytics implements generic features for operations with option chains

# Implemented dataclass analytics


### Expiry Slices <a name="eslice"></a>

[Expiry Slice](#eslice) in ```option_chain.py```

Contains call and put options dataframes per each expiry

Option chain core data and anlytics object. Generally, option chain is
a table of trading data (strikes, bids, asks, sizes, deltas, etc)
for puts and calls. These tables are indexed by contract ids and the tables are arranged by maturities.  
We term these tables as expiry slices.

implements request such as ```get_atm_vol``` , ```get_atm_option_strike``` , ```get_atm_call_id``` , 
```get_atm_call_id``` , ```get_atm_put_id```,
```get_call_delta_strike```, ```get_put_delta_strike``` 

### **Option Chain** <a name="chain"></a>

[SlicesChain](#chain) in ```option_chain.py```

Dataclass 

### **Slices Chain** <a name="chain"></a>

[SlicesChain](#chain) in ```option_chain.py```

### **OptionsDataDFs(ChainTs)** <a name="chainTs"></a>

[ChainTs](#chain_ts) in ```chain_ts.py```


dataclass containing time series of options data ```chain_ts: pd.DataFrame```
and spot data ```spot_data: pd.DataFrame```

it implements query ```get_time_slice(timestamp)``` which returns data to 
create option chain dataclass


### **OptionsDataDFs(ChainTs)** <a name="chainTs"></a>

```python 
def create_chain[test.py](..%2F..%2F..%2Fmisc%2Fderibit_websocket_Nova%2Ftest.py)_from_from_options_dfs(options_data_dfs: OptionsDataDFs,
                                       value_time: pd.Timestamp,
                                       ) -> Optional[SlicesChain]:
```




