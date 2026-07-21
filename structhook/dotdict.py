__all__ = [
    "DotDict",
]

from collections.abc import Buffer
from typing import Any

import msgspec

# ---------------------------------------------------------------------------
# Dict method names that would shadow data keys on DotDict instances.
# ---------------------------------------------------------------------------

_DICT_METHODS: frozenset[str] = frozenset(
    name for name in dir(dict) if callable(getattr(dict, name)) and not name.startswith("_")
)


class DotDict[K, V](dict[K, V]):
    """A :class:`dict` subclass with attribute-style access to keys.

    Nested dicts and lists of dicts are recursively wrapped at construction
    time, so you can chain dots arbitrarily deep::

        >>> d = DotDict({"user": {"name": "Alice", "scores": [90, 95]}})
        >>> d.user.name
        'Alice'

    Use :meth:`DotDict.decode` to go straight from JSON bytes to a ``DotDict``
    without defining a model::

        >>> d = DotDict.decode(b'{"a":{"b":1}}')
        >>> d.a.b
        1
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._wrap_nested()

    def _wrap_nested(self) -> None:
        """Recursively wrap nested dicts and lists of dicts in-place."""
        # Use dict.items() directly to avoid triggering the collision
        # check when the wrapped data happens to contain an "items" key.
        for key, value in dict.items(self):
            if isinstance(value, dict) and not isinstance(value, DotDict):
                super().__setitem__(key, DotDict(value))  # type: ignore
            elif isinstance(value, list):
                super().__setitem__(
                    key,
                    [
                        DotDict(item)
                        if isinstance(item, dict) and not isinstance(item, DotDict)
                        else item
                        for item in value
                    ],  # type: ignore
                )

    def __getattribute__(self, key: str) -> Any:
        """Intercept attribute access to detect dict-method / data-key collisions.

        When *key* matches a key stored in the underlying dict **and** a
        built-in ``dict`` method name, an :class:`AttributeError` is raised
        with a message telling the user to use bracket access.
        """
        if key.startswith("_"):
            return super().__getattribute__(key)

        try:
            value = dict.__getitem__(self, key)
        except KeyError:
            return super().__getattribute__(key)

        if key in _DICT_METHODS:
            raise AttributeError(
                f"Key {key!r} collides with a built-in dict method. Use bracket access: d[{key!r}]."
            )
        return value

    def __getitem__(self, key: K) -> V:
        return super().__getitem__(key)

    def __setitem__(self, key: K, value: V) -> None:
        if isinstance(value, dict) and not isinstance(value, DotDict):
            value = DotDict(value)  # type: ignore
        elif isinstance(value, list):
            value = [  # type: ignore
                DotDict(item) if isinstance(item, dict) and not isinstance(item, DotDict) else item
                for item in value
            ]
        super().__setitem__(key, value)

    def __getattr__(self, key: K) -> V:
        if key in _DICT_METHODS and key in self:
            raise AttributeError(
                f"Key {key!r} collides with a built-in dict method. Use bracket access: d[{key!r}]."
            )

        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'DotDict' object has no attribute '{key}'") from None

    def __setattr__(self, key: K, value: V) -> None:
        if isinstance(value, dict) and not isinstance(value, DotDict):
            self[key] = DotDict(value)  # type: ignore
        elif isinstance(value, list):
            self[key] = [  # type: ignore
                DotDict(item) if isinstance(item, dict) and not isinstance(item, DotDict) else item
                for item in value
            ]
        else:
            self[key] = value

    def __delattr__(self, key: K) -> None:
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'DotDict' object has no attribute '{key}'") from None

    @classmethod
    def decode(
        cls,
        raw: Buffer | str,
        *,
        dec_hook: Any | None = None,
    ) -> "DotDict[Any, Any]":
        """Decode JSON bytes or string directly into a :class:`DotDict`.

        This is a convenience for ``DotDict(msgspec.json.decode(raw, type=dict))``.

        Parameters
        ----------
        raw:
            JSON bytes or string to decode.
        dec_hook:
            Optional msgspec-compatible decode hook for types that msgspec
            cannot natively decode.  Passed through to
            :func:`msgspec.json.decode`.
        """
        data: dict[str, Any] = msgspec.json.decode(raw, type=dict, dec_hook=dec_hook)
        return cls(data)

    def has(self, key: K) -> bool:
        """Return ``True`` if *key* is present."""
        return key in self

    def __repr__(self) -> str:
        return f"DotDict({super().__repr__()})"

    __str__ = __repr__


# ---------------------------------------------------------------------------
# Override dict methods so that __getattribute__ can intercept attribute
# access.  Without these shims, CPython's C-level method lookup bypasses
# __getattribute__ entirely.
# ---------------------------------------------------------------------------


def _make_dict_override(name: str) -> Any:
    """Create a method override that delegates to ``dict.name``.

    The override exists so that :meth:`DotDict.__getattribute__` is reached
    during attribute lookup — native C-level method descriptors on ``dict``
    bypass it.  With the override in place, data keys that collide with a
    dict method name raise :class:`AttributeError` at access time.
    """
    original = getattr(dict, name)

    def override(self: DotDict, *args: Any, **kwargs: Any) -> Any:
        return original(self, *args, **kwargs)

    override.__name__ = name
    override.__qualname__ = f"DotDict.{name}"
    override.__doc__ = original.__doc__
    return override


for _name in _DICT_METHODS:
    setattr(DotDict, _name, _make_dict_override(_name))
