

<strong>QIS: Option Chain Analytics</strong>

Module option_chain_analytics implements generic features for operations with option chains

# Table of contents
1. [Option Chain](#chain)
    1. [Expiry Slices](#eslice)



## **Option Chain** <a name="chain"></a>
Option chain core data and anlytics object. Generally, option chain is
a table of trading data (strikes, bids, asks, sizes, deltas, etc)
for puts and calls. These tables are indexed by contract ids and the tables are arranged by maturities.  
We term these tables as slices.

### Expiry Slices <a name="eslice"></a>


```python 
option_chain.py
```




