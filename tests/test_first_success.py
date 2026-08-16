import runpy


def test_first_success_example_runs_with_expected_evidence(capsys) -> None:
    runpy.run_path('examples/first_success.py', run_name='__main__')

    output = capsys.readouterr().out
    assert 'observation_times=2' in output
    assert 'contracts_at_first_time=30' in output
    assert 'first_expiry_atm=100.00, vol=0.2057' in output
    assert "weekly_roll_expiries=['12Jan2024']" in output
