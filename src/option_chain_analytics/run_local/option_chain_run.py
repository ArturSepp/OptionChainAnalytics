"""Inspect OCA's deterministic flat-volatility expiry slice."""

from enum import Enum

import matplotlib.pyplot as plt

from option_chain_analytics.option_chain import get_flat_vol_expiry_slice


class Locals(Enum):
    """Available option-chain development diagnostics."""

    EXPIRY_SLICE_DATA = 1


def run_local(local: Locals) -> None:
    """Run the selected option-chain development diagnostic."""
    if local == Locals.EXPIRY_SLICE_DATA:
        expiry_slice = get_flat_vol_expiry_slice()
        expiry_slice.print()

    plt.show()


if __name__ == '__main__':
    run_local(local=Locals.EXPIRY_SLICE_DATA)
