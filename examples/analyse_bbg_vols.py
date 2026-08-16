
import matplotlib.pyplot as plt
import pandas as pd
import qis as qis
from qis import TimePeriod

from option_chain_analytics import local_path as lp

local_path = f"{lp.get_resource_path()}bbg_vols\\"

df = qis.load_df_from_csv(file_name="SPX Index_MNY", local_path=local_path)

print(df.columns)

vols = df[['6m100.0', '12m100.0']]
spots = df['spot_price']

qis.plot_time_series(df=vols)

periods = {'2024': TimePeriod('14Jun2024', '04Nov2024'),
           '2020': TimePeriod('17Jun2020', '04Nov2020'),
           '2016': TimePeriod('17Jun2016', '09Nov2016'),
           '2012': TimePeriod('17Jun2012', '07Nov2012'),
           '2008': TimePeriod('17Jun2008', '05Nov2008')}

vol_changes = {}
vol_start = {}
spot_returns = {}
for key, period in periods.items():
    ts_vols = period.locate(vols)
    spot = period.locate(spots)
    vol_change = ts_vols.iloc[-1, :] - ts_vols.iloc[0, :]
    vol_changes[key] = vol_change.rename({x: f"{x}-change" for x in ts_vols.columns})
    vol_start[key] = ts_vols.iloc[0, :].rename({x: f"{x}-start" for x in ts_vols.columns})
    spot_returns[key] = (spot.iloc[-1] / spot.iloc[0] - 1.0)

vol_changes = pd.DataFrame.from_dict(vol_changes, orient='index')
vol_start = pd.DataFrame.from_dict(vol_start, orient='index')
spot_returns = pd.DataFrame.from_dict(spot_returns, orient='index').rename({0: 'SPX return'}, axis=1)

df = pd.concat([spot_returns, vol_changes, vol_start], axis=1)
print(df)

qis.plot_df_table(df=qis.df_to_str(df=df, var_format='{:.1%}'),
                  index_column_name='election year')

plt.show()
