import matplotlib.pyplot as plt

from option_chain_analytics import (
    create_chain_from_from_options_dfs,
    generate_simulated_options_data,
    run_chain_report,
)


def test_chain_report_runs_with_supported_qis_api() -> None:
    options_data = generate_simulated_options_data()
    value_time = options_data.get_timeindex()[0]
    chain = create_chain_from_from_options_dfs(options_data, value_time=value_time)

    figures = run_chain_report(chain)

    assert len(figures) == 6
    assert all(figure.axes for figure in figures.values())
    plt.close('all')
