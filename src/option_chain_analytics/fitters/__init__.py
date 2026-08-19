"""Provider-independent option-chain fitting kernels."""

from option_chain_analytics.fitters.forward_discount import (
    imply_forward_discount_from_bid_ask_prices,
    imply_forward_discount_from_mark_prices,
    infer_forward_discount_from_call_put_parity,
)

__all__ = [
    'imply_forward_discount_from_bid_ask_prices',
    'imply_forward_discount_from_mark_prices',
    'infer_forward_discount_from_call_put_parity',
]
