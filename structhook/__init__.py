"""structhook - Extra field info, computed fields, and hooks for `msgspec.Struct`."""

from structhook.dotdict import DotDict
from structhook.model import (
    DictLike,
    Field,
    HookStruct,
    Stage,
    computed_field,
    deserialize,
    field,
    serialize,
    validate,
)

__all__ = [
    "DictLike",
    "DotDict",
    "Field",
    "HookStruct",
    "Stage",
    "computed_field",
    "deserialize",
    "field",
    "serialize",
    "validate",
]
