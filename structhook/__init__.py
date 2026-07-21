"""structhook - Extra field info, computed fields, and hooks for `msgspec.Struct`."""

from structhook.dotdict import DotDict
from structhook.model import (
    DictLike,
    Field,
    HookStruct,
    Stage,
    computed_field,
    field,
    post_load,
    pre_load,
    pre_unload,
)

__all__ = [
    "DictLike",
    "DotDict",
    "Field",
    "HookStruct",
    "Stage",
    "computed_field",
    "field",
    "post_load",
    "pre_load",
    "pre_unload",
]
