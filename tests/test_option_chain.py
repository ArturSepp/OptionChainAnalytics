import numpy as np

from option_chain_analytics.config import NearestStrikeOnGrid
from option_chain_analytics.option_chain import find_idx_nearest_element


def _selected_value(value: float, grid: np.ndarray, side: NearestStrikeOnGrid) -> float:
    idx = find_idx_nearest_element(value=value, a=grid, nearest_strike_on_grid=side)
    return grid[idx]


def test_below_and_above_select_the_requested_side_on_unsorted_grid() -> None:
    grid = np.array([100.0, 90.0, 110.0])

    assert _selected_value(95.0, grid, NearestStrikeOnGrid.BELOW) == 90.0
    assert _selected_value(95.0, grid, NearestStrikeOnGrid.ABOVE) == 100.0


def test_below_and_above_are_strict_for_an_exact_grid_value() -> None:
    grid = np.array([100.0, 90.0, 110.0])

    assert _selected_value(100.0, grid, NearestStrikeOnGrid.BELOW) == 90.0
    assert _selected_value(100.0, grid, NearestStrikeOnGrid.ABOVE) == 110.0


def test_below_and_above_clamp_at_grid_boundaries() -> None:
    grid = np.array([90.0, 100.0, 110.0])

    assert _selected_value(80.0, grid, NearestStrikeOnGrid.BELOW) == 90.0
    assert _selected_value(120.0, grid, NearestStrikeOnGrid.ABOVE) == 110.0
