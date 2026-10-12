"""Immutable, dependency-independent snapshots of diagnostic evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

import numpy as np
import pandas as pd


def _value(value):
    """Convert report values to strict JSON without retaining mutable objects."""
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(k): _value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [_value(v) for v in value]
    if isinstance(value, np.generic):
        return _value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported diagnostic value: {type(value).__name__}")


@dataclass(frozen=True)
class QuoteDiagnosticReport:
    """Immutable strict-JSON report; accessors return independent copies.

    Use ``from_tables`` to snapshot frames or ``from_dict`` to restore saved JSON.
    Unavailable numbers are null; the adjacent status/reason retains their meaning.
    Timestamp strings preserve UTC offsets and source-row identifiers remain strings.
    """

    _payload: str

    def __post_init__(self):
        """Validate the versioned table envelope."""
        data = json.loads(self._payload)
        if data.get("schema_version") != 1 or not isinstance(data.get("metadata"), dict):
            raise ValueError("unsupported quote diagnostic schema")
        if not isinstance(data.get("tables"), dict):
            raise ValueError("tables must be a mapping")
        for table in data["tables"].values():
            columns = table["columns"]
            if len(columns) != len(set(columns)) or any(len(r) != len(columns) for r in table["data"]):
                raise ValueError("invalid table dimensions")

    @classmethod
    def from_tables(cls, tables: Mapping[str, pd.DataFrame], metadata: Mapping) -> QuoteDiagnosticReport:
        """Copy tables and metadata into a versioned, serializable report."""
        return cls.from_dict(
            dict(
                schema_version=1,
                metadata=metadata,
                tables={
                    name: dict(columns=list(frame.columns), data=frame.to_numpy(dtype=object).tolist())
                    for name, frame in tables.items()
                },
            )
        )

    @classmethod
    def from_dict(cls, data: Mapping) -> QuoteDiagnosticReport:
        """Restore an independent report from its JSON-compatible dictionary."""
        return cls(json.dumps(_value(data), allow_nan=False, sort_keys=True))

    def to_dict(self) -> dict:
        """Return a fresh JSON-compatible dictionary."""
        return json.loads(self._payload)

    @property
    def metadata(self) -> dict:
        """Return independent conventions and provenance metadata."""
        return self.to_dict()["metadata"]

    def table(self, name: str) -> pd.DataFrame:
        """Return a fresh named table, raising KeyError for absent names."""
        table = self.to_dict()["tables"][name]
        return pd.DataFrame(table["data"], columns=table["columns"])


def _utc(value, name: str) -> pd.Timestamp:
    """Require an explicitly timezone-aware instant and normalize it to UTC."""
    time = pd.Timestamp(value)
    if pd.isna(time) or time.tzinfo is None:
        raise ValueError(f"{name} must be a valid timezone-aware timestamp")
    return time.tz_convert("UTC")
