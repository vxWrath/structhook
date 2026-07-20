"""structhook - Extra field info, computed fields, and hooks for `msgspec.Struct`."""

from structhook.model import (
    BaseModel,
    DictLike,
    Field,
    Stage,
    computed_field,
    deserialize,
    field,
    serialize,
    validate,
)

__all__ = [
    "BaseModel",
    "DictLike",
    "Field",
    "Stage",
    "computed_field",
    "deserialize",
    "field",
    "serialize",
    "validate",
]
