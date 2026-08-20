"""Canonical physical-cache conventions shared by OCA provider adapters.

Provider modules first normalize their source-specific columns and conventions
into the complete :class:`~option_chain_analytics.option_chain.SliceColumn`
schema. This module then gives CBOE, Tardis, and ThetaData caches one physical
representation: identifiers are Arrow strings, timestamps are nanosecond UTC,
and numerical observations are ``float64``.

The helpers deliberately contain no provider pricing or timestamp policy. They
only enforce schema order and dtypes, attach auditable Parquet metadata, and
route default caches away from raw-data directories. PyArrow remains a lazy
dependency and is imported only when a cache is read or written.
"""

from pathlib import Path
from typing import Any, Dict

import pandas as pd

from option_chain_analytics.option_chain import SliceColumn

NORMALIZED_OPTIONS_CACHE_FORMAT = 'option_chain_analytics.options.normalized'
NORMALIZED_OPTIONS_CACHE_SCHEMA_VERSION = '3'
NORMALIZED_OPTIONS_DTYPE_POLICY = 'slice_column_string_timestamp_utc_float64_v1'

OCA_STRING_COLUMNS = (
    SliceColumn.CONTRACT.value,
    SliceColumn.UNDERLYING_INDEX.value,
    SliceColumn.MATURITY_ID.value,
    SliceColumn.OPTION_TYPE.value,
)
OCA_TIMESTAMP_COLUMNS = (
    SliceColumn.EXCHANGE_TIME.value,
    SliceColumn.EXPIRY.value,
)
OCA_NUMERIC_COLUMNS = tuple(
    column.value
    for column in SliceColumn
    if column.value not in OCA_STRING_COLUMNS and column.value not in OCA_TIMESTAMP_COLUMNS
)

def _coerce_oca_options_frame(chain_ts: pd.DataFrame) -> pd.DataFrame:
    """Coerce an option panel to OCA's canonical column order and dtypes.

    Parameters
    ----------
    chain_ts : pandas.DataFrame
        Long-form option observations containing every ``SliceColumn`` field.

    Returns
    -------
    pandas.DataFrame
        A copy ordered exactly like ``SliceColumn`` with UTC timestamps, pandas
        string identifiers, and ``float64`` numerical columns.

    Raises
    ------
    ValueError
        If any canonical option-observation column is missing.
    """
    columns = [column.value for column in SliceColumn]
    missing = set(columns).difference(chain_ts.columns)
    if missing:
        raise ValueError(f"missing OCA option columns: {sorted(missing)}")

    chain_ts = chain_ts.loc[:, columns].copy()
    for column in OCA_STRING_COLUMNS:
        chain_ts[column] = chain_ts[column].astype('string')
    for column in OCA_TIMESTAMP_COLUMNS:
        chain_ts[column] = pd.to_datetime(chain_ts[column], utc=True)
    for column in OCA_NUMERIC_COLUMNS:
        chain_ts[column] = pd.to_numeric(chain_ts[column], errors='coerce').astype('float64')
    return chain_ts


def _get_oca_options_arrow_schema() -> Any:
    """Create the provider-neutral Arrow schema used by normalized caches.

    Returns
    -------
    pyarrow.Schema
        Schema matching ``SliceColumn`` order and OCA's timestamp, string, and
        numeric dtype policy.

    Notes
    -----
    PyArrow is imported inside the function so importing OCA or using simulated
    data does not require the optional cache dependency.
    """
    import pyarrow as pa

    fields = []
    for column in SliceColumn:
        if column.value in OCA_STRING_COLUMNS:
            dtype = pa.string()
        elif column.value in OCA_TIMESTAMP_COLUMNS:
            dtype = pa.timestamp('ns', tz='UTC')
        else:
            dtype = pa.float64()
        fields.append(pa.field(column.value, dtype))
    return pa.schema(fields)


def _to_oca_options_arrow_table(chain_ts: pd.DataFrame, metadata: Dict[bytes, bytes]) -> Any:
    """Convert an option panel to a schema-checked Arrow table.

    Parameters
    ----------
    chain_ts : pandas.DataFrame
        Provider-normalized observations in the complete ``SliceColumn`` schema.
    metadata : dict[bytes, bytes]
        Provider, policy, schema-version, and source-fingerprint metadata to
        merge into the Arrow schema.

    Returns
    -------
    pyarrow.Table
        Canonically typed table ready for atomic Parquet persistence.
    """
    import pyarrow as pa

    table = pa.Table.from_pandas(
        _coerce_oca_options_frame(chain_ts),
        schema=_get_oca_options_arrow_schema(),
        preserve_index=False,
        safe=True,
    )
    return table.replace_schema_metadata({**(table.schema.metadata or {}), **metadata})


def _read_cache_metadata(cache_path: Path) -> Dict[str, str]:
    """Read the OCA-owned metadata namespace from a Parquet cache.

    Parameters
    ----------
    cache_path : pathlib.Path
        Existing normalized Parquet cache.

    Returns
    -------
    dict[str, str]
        Decoded metadata whose keys begin with ``oca_``. Foreign Parquet
        metadata, including pandas internals, is intentionally omitted.
    """
    import pyarrow.parquet as pq

    raw_metadata = pq.ParquetFile(cache_path).metadata.metadata or {}
    return {key.decode(): value.decode() for key, value in raw_metadata.items() if key.startswith(b'oca_')}


def _normalized_cache_directory(local_path: str, default_source_path: str, default_cache_path: str) -> str:
    """Resolve central versus explicitly co-located normalized-cache storage.

    Parameters
    ----------
    local_path : str
        Provider source directory requested by the caller.
    default_source_path : str
        Provider's centrally configured raw-data directory.
    default_cache_path : str
        Provider's centrally configured normalized-cache directory.

    Returns
    -------
    str
        ``default_cache_path`` when the standard source directory is used;
        otherwise ``local_path`` so explicit custom workflows remain co-located.
    """
    if Path(local_path).resolve() == Path(default_source_path).resolve():
        return default_cache_path
    return local_path
