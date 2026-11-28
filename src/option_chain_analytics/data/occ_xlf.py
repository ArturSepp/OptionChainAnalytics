"""Contract identifiers and exercise values for the 2016 XLF distribution."""

from datetime import date
from math import isfinite

XLF_DISTRIBUTION_DATE = date(2016, 9, 19)
XLF1_LAST_EXPIRY = date(2018, 1, 19)
XLF1_MULTIPLIER = 100
XLF1_XLRE_SHARES = 13
_ADJUSTED_ROOTS = {'XLF': 'XLF1', '1XLF': '1XLF1', '2XLF': '2XLF1'}


def xlf_contract_at_session(contract: str, opened_on: date, session: date) -> str:
    """Resolve a held OCA XLF contract across the OCC 39575 adjustment.

    Dates are US trading-session dates. Pass the contract ID from the open
    transaction and its original session. The expiration, strike and right
    remain unchanged when the old root migrates to its adjusted root. A new
    standard-root position uses its original ID throughout.
    """
    if session < opened_on:
        raise ValueError('session precedes the opening session')
    root, separator, terms = contract.partition('-')
    if not separator or not terms or root not in {*_ADJUSTED_ROOTS, *_ADJUSTED_ROOTS.values()}:
        raise ValueError(f'expected an OCA XLF contract ID, got {contract!r}')
    if opened_on < XLF_DISTRIBUTION_DATE <= session and root in _ADJUSTED_ROOTS:
        return f'{_ADJUSTED_ROOTS[root]}-{terms}'
    return contract


def xlf1_intrinsic_value(
    *, strike: float, option_type: str, xlf_price: float, xlre_price: float, cash_in_lieu: float,
) -> float:
    """Return XLF1 exercise value in USD per contract.

    Supply contemporaneous unadjusted XLF and XLRE settlement prices and the
    final OCC cash-in-lieu amount in USD per contract for 0.9146 XLRE shares.
    The strike and quoted premium each retain their 100 multiplier.
    """
    if not all(isfinite(value) and value > 0 for value in (strike, xlf_price, xlre_price, cash_in_lieu)):
        raise ValueError('strike, component prices and verified cash in lieu must be positive and finite')
    if option_type not in ('C', 'P'):
        raise ValueError("option_type must be 'C' or 'P'")
    deliverable = XLF1_MULTIPLIER * xlf_price + XLF1_XLRE_SHARES * xlre_price + cash_in_lieu
    intrinsic = deliverable - XLF1_MULTIPLIER * strike
    return max(0.0, intrinsic if option_type == 'C' else -intrinsic)
