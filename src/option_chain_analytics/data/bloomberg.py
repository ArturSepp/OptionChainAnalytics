"""Fetch and persist Bloomberg BVOL volatility-surface time series.

TODO: Map the bbg-fetch BVOL tenor/moneyness surface to synthetic option
prices, with a deterministic option-maturity roll convention, for tests and
visualisations. Until then, the source-checkout diagnostic in
``option_chain_analytics.data.run_local.bloomberg_run`` stores BVOL inputs
under OCA's centralized ``bbg_vols`` resource folder and does not present them
as observed option prices.
"""
