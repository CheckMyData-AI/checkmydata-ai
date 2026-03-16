from typing import Any


def serialize_value(val: Any) -> Any:
    """Convert a value to a JSON-safe representation."""
    if val is None:
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    if isinstance(val, bytes):
        return val.hex()
    return str(val)
