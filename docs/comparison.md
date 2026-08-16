# Choosing an option-data tool

This comparison was checked on 2026-08-16 against each project's primary documentation. The tools
solve overlapping but different problems; none is a universal replacement for the others.

| Tool | Primary scope | Historical point-in-time panel | Provider coupling | Choose it when |
|---|---|---|---|---|
| OptionChainAnalytics | Source-neutral option observations, expiry slices, historical chain reconstruction, and research queries | Native `OptionsDataDFs` long panel and exact-time reconstruction | Adapters are separate from the container; local/provider access is caller-managed | You already have option observations and need one auditable schema feeding empirical research or backtests. |
| [QuantLib-Python 1.40 docs](https://quantlib-python-docs.readthedocs.io/en/latest/) | Broad derivatives instruments, term structures, models, and pricing engines | Not presented as a historical option-feed panel container | Market inputs are constructed by the user | You need instrument valuation, calibration, or a broad quantitative-finance engine. |
| [OpenBB option-chain model](https://docs.openbb.co/odp/python/data_models/OptionsChains) and [surface API](https://docs.openbb.co/python/reference/derivatives/options/surface/) | Provider-normalised retrieval and current option-chain/surface workflows | Depends on provider endpoint and entitlements rather than one OCA-style local panel contract | Provider selection is central to retrieval | You want a unified data platform and supported provider connectors more than a specialised local research container. |
| [Optopsy](https://github.com/goldspanlabs/optopsy) | Options strategy backtesting, simulation, and CLI workflows | Consumes strategy-backtest data formats rather than acting primarily as a feed-neutral chain container | Input data is user-supplied; strategy templates are built in | You want ready-made multi-leg options strategy simulations and its licensing/runtime constraints fit your project. |

OCA deliberately does not replace QuantLib's pricing engines, OpenBB's provider platform, or
Optopsy's strategy simulator. In Artur Sepp's package stack, option valuation stays in
`vanilla-option-pricers` and portfolio/QF-paper backtests stay in SigmaStrats. OCA's narrower role is
to make the option-data layer explicit and reproducible.
