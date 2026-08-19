import runpy
import sys

import pytest


@pytest.mark.parametrize(
    ('metric', 'expected', 'excluded'),
    [
        ('atm', 'atm_vol=0.250000 (25.0000%)', 'skew_25d='),
        ('skew', 'skew_25d=0.000000', 'atm_vol='),
    ],
)
def test_thetadata_example_selects_requested_metric(
    capsys,
    monkeypatch,
    metric: str,
    expected: str,
    excluded: str,
) -> None:
    monkeypatch.setattr(sys, 'argv', ['fetch_thetadata_eod.py', '--metric', metric])

    runpy.run_path('examples/fetch_thetadata_eod.py', run_name='__main__')

    output = capsys.readouterr().out
    assert 'ticker=DEMO' in output
    assert 'expiration=2026-09-18' in output
    assert expected in output
    assert excluded not in output


def test_thetadata_example_exposes_callable_function(capsys) -> None:
    example = runpy.run_path('examples/fetch_thetadata_eod.py')

    result = example['display_thetadata_eod_metrics'](
        ticker='aapl',
        value_date='2026-07-24',
        expiration='2026-08-21',
        metric='atm',
        is_live=False,
    )

    assert result['ticker'] == 'AAPL'
    assert result['expiration'].isoformat() == '2026-08-21'
    assert result['atm_vol'] == pytest.approx(0.25)
    assert result['skew'] is None
    assert 'ticker=AAPL' in capsys.readouterr().out
