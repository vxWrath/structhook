"""Core model wrapper for msgspec.

Provides :class:`HookStruct`, a drop-in replacement for :class:`msgspec.Struct`
that adds:

* **Field metadata** - :func:`field` / :class:`Field` with ``exclude`` and
  ``extra`` options.
* **Lifecycle hooks** - :func:`serialize`, :func:`deserialize`, and
  :func:`validate` decorators for per-field transform pipelines.
  These fire on **every** encode / decode of the field.
* **msgspec codec hooks** - :meth:`HookStruct.msgspec_enc_hook` and
  :meth:`HookStruct.msgspec_dec_hook` static methods that fire **only** when
  msgspec encounters a type it doesn't natively handle.  Override these to
  teach msgspec about custom types (e.g. ``UUID``, ``Money``, ``DotDict``).
* **Computed fields** - :func:`computed_field` for read-only derived values
  that appear in serialized output.
* **Dict-like access** - ``model["key"]`` / ``model["key"] = value`` mapping
  API.
* **Controlled output** - :meth:`HookStruct.dump` with ``include`` filtering,
  ``fire_hooks`` toggle, and JSON / Python mode selection.
"""

from collections.abc import Buffer, Callable, Sequence
from enum import StrEnum
from typing import (
    Any,
    ClassVar,
    Literal,
    Protocol,
    Self,
    dataclass_transform,
    get_origin,
)

import msgspec
from msgspec import NODEFAULT, Struct, StructMeta, json, structs
from msgspec._core import Factory as _Factory

from structhook.dotdict import DotDict

__all__ = [
    "HookStruct",
    "DictLike",
    "Field",
    "Stage",
    "computed_field",
    "deserialize",
    "field",
    "serialize",
    "validate",
]

# ---------------------------------------------------------------------------
# Dict-like protocol
# ---------------------------------------------------------------------------


class DictLike(Protocol):
    """A dict-like object: has string keys and supports ``__getitem__``.

    This is the minimal interface needed by :meth:`HookStruct.convert` - any
    type that can be passed to ``dict()`` and indexed by string keys works.
    """

    def keys(self) -> Any: ...
    def __getitem__(self, key: str, /) -> Any: ...


# ---------------------------------------------------------------------------
# Field descriptor
# ---------------------------------------------------------------------------


class Field:
    """Descriptor for a model field with optional metadata.

    Parameters
    ----------
    default:
        Default value for the field.  Use :data:`msgspec.NODEFAULT` to mark it
        as required.
    default_factory:
        A zero-argument callable that produces a default value.  Mutually
        exclusive with *default*.
    name:
        Override the serialized field name (maps to *msgspec*'s ``name``).
    exclude:
        If ``True`` the field is excluded from encoding / ``dump()`` output.
    extra:
        Arbitrary user-defined metadata.  Not consumed by the framework -
        intended for third-party tooling (e.g. code-generation, OpenAPI
        schema builders, ORM bridges).
    """

    def __init__(
        self,
        *,
        default: Any = NODEFAULT,
        default_factory: Any | Callable[[], Any] | None = NODEFAULT,
        name: str | None = None,
        exclude: bool = False,
        extra: Any | None = None,
    ) -> None:
        self.default = default
        self.default_factory = default_factory
        self.name = name

        self.exclude = exclude
        self.extra = extra

    def __repr__(self) -> str:
        return (
            f"Field(default={self.default!r}, default_factory={self.default_factory!r}, "
            f"name={self.name!r}, is_required={self.is_required!r}, exclude={self.exclude!r})"
        )

    @property
    def is_required(self) -> bool:
        return self.default is NODEFAULT and self.default_factory is NODEFAULT


def field(
    *,
    default: Any = NODEFAULT,
    default_factory: Any | Callable[[], Any] | None = NODEFAULT,
    name: str | None = None,
    exclude: bool = False,
    extra: Any | None = None,
) -> Any:
    """Declare a model field with extra metadata.

    Returns a :class:`Field` instance that the :class:`HookStructMeta` metaclass
    converts into a native :func:`msgspec.field` at class-creation time.
    """
    if default is not NODEFAULT and default_factory is not NODEFAULT:
        raise ValueError("Cannot specify both default and default_factory")

    return Field(
        default=default,
        default_factory=default_factory,
        name=name,
        exclude=exclude,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Hook decorators
# ---------------------------------------------------------------------------


class Stage(StrEnum):
    """Enum for hook pipeline stages."""

    SERIALIZE = "serialize"
    DESERIALIZE = "deserialize"
    VALIDATE = "validate"


def serialize(field_or_fields: str | Sequence[str]) -> Callable[..., Any]:
    """Register a function as a *serialize* hook for the given field(s).

    The hook receives ``(model_instance, current_value)`` and must return the
    serialized value.  Serialize hooks fire **after** computed fields and
    excluded fields are processed, but **before** JSON encoding.
    """

    if isinstance(field_or_fields, str):
        field_or_fields = [field_or_fields]

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.__stage__ = Stage.SERIALIZE
        func.__fields__ = field_or_fields
        return func

    return decorator


def deserialize(field_or_fields: str | Sequence[str]) -> Callable[..., Any]:
    """Register a function as a *deserialize* hook for the given field(s).

    The hook receives ``(model_class, raw_value)`` and must return the
    deserialized value.  It runs on the raw decoded dict **before** struct
    conversion, so the value may still be an un-coerced JSON primitive.
    """

    if isinstance(field_or_fields, str):
        field_or_fields = [field_or_fields]

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.__stage__ = Stage.DESERIALIZE
        func.__fields__ = field_or_fields
        return func

    return decorator


def validate(field_or_fields: str | Sequence[str]) -> Callable[..., Any]:
    """Register a function as a *validate* hook for the given field(s).

    The hook receives ``(model_class, converted_value)`` and must return the
    (possibly transformed) value.  It runs **after** struct conversion, so the
    value is already coerced to the field's declared type.

    .. warning::
        Validate hooks use ``object.__setattr__`` to mutate the model after
        construction and are therefore **incompatible** with ``frozen=True``.
    """

    if isinstance(field_or_fields, str):
        field_or_fields = [field_or_fields]

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func.__stage__ = Stage.VALIDATE
        func.__fields__ = field_or_fields
        return func

    return decorator


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------


class computedproperty(property):
    """A :class:`property` subclass that marks the method as a computed field."""

    __slots__ = ()
    __computed_field__ = True


def computed_field(func: Callable[..., Any]) -> property:
    """Mark a method as a *computed field*.

    The method becomes a read-only property whose value is injected into
    ``dump()`` / ``encode()`` output but is **not** stored in the underlying
    struct.

    Example::

        class User(HookStruct):
            first: str
            last: str

            @computed_field
            def full_name(self) -> str:
                return f"{self.first} {self.last}"
    """
    return computedproperty(func)


# ---------------------------------------------------------------------------
# Metaclass
# ---------------------------------------------------------------------------


@dataclass_transform(field_descriptors=(field,), kw_only_default=True)  # type: ignore
class HookStructMeta(StructMeta):
    """Metaclass that wires up hooks, computed fields, and encode/decode logic."""

    def __new__(
        mcls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        fields: list[tuple[str, Field]] = []
        computed_fields: list[str] = []

        hooks: dict[Stage, dict[str, list[Callable[..., Any]]]] = {
            Stage.SERIALIZE: {},
            Stage.DESERIALIZE: {},
            Stage.VALIDATE: {},
        }

        for key, value in namespace.items():
            if isinstance(value, Field):
                fields.append((key, value))
                namespace[key] = msgspec.field(
                    default=value.default,
                    default_factory=value.default_factory,
                    name=value.name,
                )  # type: ignore

            elif callable(value) and hasattr(value, "__stage__") and hasattr(value, "__fields__"):
                for hook_field in value.__fields__:
                    hooks[value.__stage__].setdefault(hook_field, []).append(value)

            elif isinstance(value, computedproperty) and getattr(
                value, "__computed_field__", False
            ):
                computed_fields.append(key)

        # --- inherit parent field metadata ---------------------------------

        parent_fields: dict[str, Field] = {}
        for base in bases:
            for field_name, field in getattr(base, "__fields__", {}).items():
                if field_name not in parent_fields:
                    parent_fields[field_name] = field

        # Propagate kw_only and dict from parent HookStruct subclasses.
        # msgspec does not expose these in __struct_config__, so we track
        # them ourselves via __kw_only__ / __dict__ sentinel attributes.
        for base in bases:
            if getattr(base, "__kw_only__", False):
                kwargs.setdefault("kw_only", True)
            if getattr(base, "__has_dict__", False):
                kwargs.setdefault("dict", True)

        cls = super().__new__(mcls, name, bases, namespace, **kwargs)

        cls.__kw_only__ = kwargs.get("kw_only", False)  # type: ignore
        cls.__has_dict__ = kwargs.get("dict", False)  # type: ignore

        # After super().__new__, __struct_config__ is available - use it as
        # the authoritative source (handles inheritance correctly).
        is_frozen = cls.__struct_config__.frozen

        # --- rebuild the canonical Field list (merges parent fields) -------

        npos = len(cls.__struct_fields__) - len(cls.__struct_defaults__)
        for i, (field_name, default_obj) in enumerate(
            zip(
                cls.__struct_fields__,
                (NODEFAULT,) * npos + cls.__struct_defaults__,
                strict=True,
            )
        ):
            default = default_factory = NODEFAULT

            if isinstance(default_obj, _Factory):
                default_factory = default_obj.factory  # type: ignore

            elif default_obj is not NODEFAULT:
                default = default_obj

            if not any(key == field_name for key, _ in fields):
                parent_field = parent_fields.get(field_name)
                fields.insert(
                    i,
                    (
                        field_name,
                        Field(
                            default=default,
                            default_factory=default_factory,
                            name=field_name,
                            exclude=parent_field.exclude if parent_field else False,
                            extra=parent_field.extra if parent_field else None,
                        ),
                    ),
                )

        # --- inherit parent hooks & computed fields ------------------------

        for base in bases:
            for stage in Stage:
                base_hooks: dict[str, list[Callable[..., Any]]] = getattr(
                    base, f"__{stage.value}_hooks__", {}
                )
                for hook_field, funcs in base_hooks.items():
                    existing = hooks[stage].setdefault(hook_field, [])
                    for func in funcs:
                        if func not in existing:
                            existing.insert(0, func)

            for cf in getattr(base, "__computed_fields__", ()):
                if cf not in computed_fields:
                    computed_fields.insert(0, cf)

        # ------------------------------------------------------------------

        all_fields = dict(fields)
        computed_fields_tuple = tuple(computed_fields)
        excluded_fields = frozenset(name for name, f in all_fields.items() if f.exclude)

        cls.__fields__ = all_fields  # type: ignore
        cls.__computed_fields__ = computed_fields_tuple  # type: ignore
        cls.__excluded_fields__ = excluded_fields  # type: ignore
        cls.__serialize_hooks__ = hooks[Stage.SERIALIZE]  # type: ignore
        cls.__deserialize_hooks__ = hooks[Stage.DESERIALIZE]  # type: ignore
        cls.__validate_hooks__ = hooks[Stage.VALIDATE]  # type: ignore

        # --- guard: frozen + validate hooks ---------------------------------

        if is_frozen and cls.__validate_hooks__:  # type: ignore
            raise TypeError(
                f"Cannot create frozen model {name!r} with validate hooks. "
                f"Validate hooks require post-construction mutation via "
                f"object.__setattr__, which is incompatible with frozen=True."
            )

        # --- feature flags --------------------------------------------------

        cls.__has_encode_features__ = bool(  # type: ignore
            computed_fields_tuple or excluded_fields or cls.__serialize_hooks__  # type: ignore
        )
        cls.__has_decode_features__ = bool(cls.__deserialize_hooks__ or cls.__validate_hooks__)  # type: ignore

        # --- build per-class encoder / decoders -------------------------------

        # Each class gets its own encoder and decoders so that subclasses can
        # override msgspec_enc_hook / msgspec_dec_hook.
        _encoder = json.Encoder(enc_hook=cls.msgspec_enc_hook)  # type: ignore
        _dict_decoder = json.Decoder(dict, dec_hook=cls.msgspec_dec_hook)  # type: ignore
        _typed_decoder = json.Decoder(cls, dec_hook=cls.msgspec_dec_hook)  # type: ignore
        cls.__json_encoder__ = _encoder  # type: ignore

        # --- build _to_builtins / _encode -----------------------------------

        if not cls.__has_encode_features__:  # type: ignore

            def _to_builtins(self: HookStruct, fire_hooks: bool = True) -> dict[str, Any]:
                return msgspec.to_builtins(self, enc_hook=type(self).msgspec_enc_hook)

            def _encode(self: HookStruct) -> bytes:
                # Fast path: encode the Struct directly - no intermediate dict.
                return _encoder.encode(self)

        else:
            _encode_excluded_fields = cls.__excluded_fields__  # type: ignore
            _encode_computed_fields = cls.__computed_fields__  # type: ignore
            _encode_serialize_hooks = cls.__serialize_hooks__  # type: ignore

            def _to_builtins(self: HookStruct, fire_hooks: bool = True) -> dict[str, Any]:
                data: dict[str, Any] = msgspec.to_builtins(
                    self, enc_hook=type(self).msgspec_enc_hook
                )

                for field in _encode_excluded_fields:
                    data.pop(field, None)

                for field in _encode_computed_fields:
                    data[field] = getattr(self, field)

                if fire_hooks:
                    for field, funcs in _encode_serialize_hooks.items():
                        if field in data:
                            for func in funcs:
                                data[field] = func(self, data[field])

                return data

            def _encode(self: HookStruct) -> bytes:
                return _encoder.encode(_to_builtins(self))

        # --- build _shared_convert ------------------------------------------

        _shared_validate_hooks = cls.__validate_hooks__  # type: ignore

        def _shared_convert(model: HookStruct) -> HookStruct:
            for field, funcs in _shared_validate_hooks.items():
                for func in funcs:
                    object.__setattr__(model, field, func(cls, getattr(model, field)))

            return model

        # --- build _decode / _convert ---------------------------------------

        if not cls.__has_decode_features__:  # type: ignore

            def _decode(raw: bytes) -> HookStruct:
                return _typed_decoder.decode(raw)

            def _convert(data: DictLike) -> HookStruct:
                # Fast path: no hooks - convert directly.
                return msgspec.convert(data, cls, dec_hook=cls.msgspec_dec_hook)  # type: ignore

        else:
            _decode_deserialize_hooks = cls.__deserialize_hooks__  # type: ignore
            _decode_validate_hooks = cls.__validate_hooks__  # type: ignore

            def _decode(raw: bytes) -> HookStruct:
                data: dict[str, Any] = _dict_decoder.decode(raw)

                for field, funcs in _decode_deserialize_hooks.items():
                    if field in data:
                        for func in funcs:
                            data[field] = func(cls, data[field])

                obj = msgspec.convert(data, cls, dec_hook=cls.msgspec_dec_hook)  # type: ignore

                for field, funcs in _decode_validate_hooks.items():
                    for func in funcs:
                        object.__setattr__(obj, field, func(cls, getattr(obj, field)))

                return obj

            def _convert(data: DictLike) -> HookStruct:
                data_dict = dict(data)

                for field, funcs in _decode_deserialize_hooks.items():
                    if field in data_dict:
                        for func in funcs:
                            data_dict[field] = func(cls, data_dict[field])

                return _shared_convert(
                    msgspec.convert(data_dict, cls, dec_hook=cls.msgspec_dec_hook)  # type: ignore
                )

        cls.__to_builtins_func__ = _to_builtins  # type: ignore
        cls.__encode_func__ = _encode  # type: ignore
        cls.__decode_func__ = _decode  # type: ignore
        cls.__convert_func__ = _convert  # type: ignore

        return cls


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class HookStruct(Struct, kw_only=True, dict=True, metaclass=HookStructMeta):
    """Base class for msgspec-backed models with hooks, computed fields, and
    field exclusion.

    Subclass this instead of :class:`msgspec.Struct` to get hooks, computed
    fields, and field-exclusion support.

    **Two kinds of hooks**

    ``structhook`` provides two distinct hook systems that serve different
    purposes:

    .. list-table::
       :header-rows: 1

       * - Hook
         - Scope
         - When it fires
         - Override via
       * - :func:`serialize` / :func:`deserialize` / :func:`validate`
         - A specific **field**
         - **Every** encode / decode of that field
         - Decorator on a method
       * - :meth:`msgspec_enc_hook` / :meth:`msgspec_dec_hook`
         - A **type** msgspec doesn't natively handle
         - **Only** when that type is encountered
         - ``@staticmethod`` override on a subclass

    .. warning::
        ``frozen=True`` is incompatible with :func:`validate` hooks (they
        require post-construction mutation via ``object.__setattr__``).
        Creating a frozen model with validate hooks raises ``TypeError`` at
        class-definition time.

        Likewise, the mapping API (``model["key"] = value``) uses
        ``object.__setattr__`` and will fail on frozen instances at runtime.
    """

    __fields__: ClassVar[dict[str, Field]]
    __computed_fields__: ClassVar[tuple[str, ...]]
    __excluded_fields__: ClassVar[frozenset[str]]

    __serialize_hooks__: ClassVar[dict[str, list[Callable[..., Any]]]]
    __deserialize_hooks__: ClassVar[dict[str, list[Callable[..., Any]]]]
    __validate_hooks__: ClassVar[dict[str, list[Callable[..., Any]]]]

    __has_encode_features__: ClassVar[bool]
    __has_decode_features__: ClassVar[bool]

    __to_builtins_func__: ClassVar[Callable[..., dict[str, Any]]]
    __encode_func__: ClassVar[Callable[[Self], bytes]]
    __decode_func__: ClassVar[Callable[[Buffer | str], Self]]
    __convert_func__: ClassVar[Callable[[DictLike], Self]]
    __json_encoder__: ClassVar[json.Encoder]

    # --------------- msgspec encode / decode hooks -----------------------

    @staticmethod
    def msgspec_enc_hook(obj: Any) -> Any:
        """Encode hook called by msgspec **only** for types it cannot natively encode.

        .. important::

           This hook fires **only** when msgspec encounters a type it doesn't
           know how to serialize (e.g. ``DotDict``, ``UUID``, a custom class).
           It does **not** fire for ``str``, ``int``, ``list``, or any other
           type msgspec handles natively.

           If you want a hook that fires on **every** encode of a specific
           field, use :func:`serialize` instead.

        The hook receives a single object and must return a JSON-serializable
        value (``dict``, ``list``, ``str``, ``int``, ``float``, ``bool``, or
        ``None``).  It is passed as the ``enc_hook`` parameter to
        :class:`msgspec.json.Encoder` and :func:`msgspec.to_builtins`.

        **Override this in subclasses** to add custom JSON encoding for your
        types.  Always call the parent implementation as a fallback so that
        :class:`DotDict` encoding (and any other base-type handling) continues
        to work::

            from uuid import UUID

            class MyModel(HookStruct):
                id: UUID
                name: str

                @staticmethod
                def msgspec_enc_hook(obj):
                    if isinstance(obj, UUID):
                        return str(obj)
                    # Fall back to default handling (DotDict, etc.)
                    return HookStruct.msgspec_enc_hook(obj)

        .. warning::

            This hook fires for **every** object msgspec cannot natively
            encode.  Keep it fast and side-effect-free — do not mutate the
            object or its attributes.
        """
        if isinstance(obj, DotDict):
            return dict(obj)
        raise TypeError(f"Cannot encode object of type {type(obj)!r}")

    @staticmethod
    def msgspec_dec_hook(typ: type[Any], obj: Any) -> Any:
        """Decode hook called by msgspec **only** for types it cannot natively decode.

        .. important::

           This hook fires **only** when msgspec encounters a type it doesn't
           know how to deserialize (e.g. ``DotDict``, ``UUID``, a custom class).
           It does **not** fire for ``str``, ``int``, ``list``, or any other
           type msgspec handles natively.

           If you want a hook that fires on **every** decode of a specific
           field, use :func:`deserialize` instead.

        The hook receives the **target type** and the raw JSON value, and must
        return an instance of the target type.  It is passed as the
        ``dec_hook`` parameter to :class:`msgspec.json.Decoder` and
        :func:`msgspec.convert`.

        **Override this in subclasses** to add custom JSON decoding for your
        types.  Always call the parent implementation as a fallback so that
        :class:`DotDict` decoding (and any other base-type handling) continues
        to work::

            from uuid import UUID

            class MyModel(HookStruct):
                id: UUID
                name: str

                @staticmethod
                def msgspec_dec_hook(typ, obj):
                    if typ is UUID:
                        return UUID(obj)
                    # Fall back to default handling (DotDict, etc.)
                    return HookStruct.msgspec_dec_hook(typ, obj)

        .. warning::

            This hook fires for **every** type msgspec cannot natively
            decode.  Keep it fast and side-effect-free — do not mutate
            the input object.
        """
        origin = get_origin(typ) or typ
        if origin is DotDict or (isinstance(origin, type) and issubclass(origin, DotDict)):
            return DotDict(obj)
        raise TypeError(f"Cannot decode into type {typ!r}")

    # ---------------------------- mapping API -----------------------------

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, val: Any) -> None:
        object.__setattr__(self, key, val)

    # ---------------------------- serialization ---------------------------

    def encode(self) -> bytes:
        """Encode the model to JSON bytes (always fires hooks)."""
        return self.__class__.__encode_func__(self)

    def dump(
        self,
        mode: Literal["python", "json"] = "python",
        *,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
        fire_hooks: bool = True,
    ) -> dict[str, Any]:
        """Convert the model to a plain Python dict (or JSON round-tripped dict).

        Parameters
        ----------
        mode:
            ``"python"`` returns the result of :func:`msgspec.to_builtins`
            (plus computed fields, minus excluded fields, and optionally
            serialize hooks).  ``"json"`` round-trips through JSON so that
            dates, UUIDs, etc. are rendered as their JSON string forms.
        include:
            If provided, return only the named fields (dropping any that
            aren't present).  Mutually exclusive with *exclude*.
        exclude:
            If provided, return all fields except the named ones.  Mutually
            exclusive with *include*.
        fire_hooks:
            If ``False``, skip serialize hooks.  Excluded and computed fields
            are still processed.  Defaults to ``True``.

        Raises
        ------
        ValueError
            If both *include* and *exclude* are provided.
        """
        if include is not None and exclude is not None:
            raise ValueError("include and exclude are mutually exclusive")

        data = self.__class__.__to_builtins_func__(self, fire_hooks=fire_hooks)

        if mode == "json":
            data = msgspec.json.decode(type(self).__json_encoder__.encode(data))

        if include is not None:
            return {field: data[field] for field in include if field in data}
        if exclude is not None:
            return {field: data[field] for field in data if field not in exclude}
        return data

    def to_positional(
        self,
        mode: Literal["python", "json"] = "python",
        *,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
        fire_hooks: bool = True,
    ) -> tuple[Any, ...]:
        """Alias for :meth:`dump` but converts the result to a tuple of values.

        See :meth:`dump` for details.
        """
        data = self.dump(mode, include=include, exclude=exclude, fire_hooks=fire_hooks)
        return tuple(data.values())

    # ---------------------------- deserialization -------------------------

    @classmethod
    def decode(cls, raw_data: Buffer | str) -> Self:
        """Decode JSON bytes into a model instance."""
        return cls.__decode_func__(raw_data)

    @classmethod
    def convert(cls, data: DictLike) -> Self:
        """Convert a dict-like object into a model instance."""
        return cls.__convert_func__(data)

    # ---------------------------- utilities -------------------------------

    def copy(self, **changes: Any) -> Self:
        """Return a shallow copy with the given field values replaced.

        Raises
        ------
        TypeError
            If any key in *changes* names a computed field - those are
            derived from other fields and cannot be set directly.
        """
        for field in self.__computed_fields__:
            if field in changes:
                raise TypeError(
                    f"Cannot set computed field {field!r} via copy(). "
                    f"Computed fields are derived from other fields."
                )
        return structs.replace(self, **changes)
