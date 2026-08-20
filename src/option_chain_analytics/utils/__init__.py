"""Provider-independent option-chain utilities."""

from option_chain_analytics.utils.forward_discount import (
    imply_forward_discount_from_bid_ask_prices,
    imply_forward_discount_from_mark_prices,
    infer_forward_discount_from_call_put_parity,
)

__all__ = [
    'imply_forward_discount_from_bid_ask_prices',
    'imply_forward_discount_from_mark_prices',
    'infer_forward_discount_from_call_put_parity',
]
