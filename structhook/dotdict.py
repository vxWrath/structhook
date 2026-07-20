__all__ = [
    "DotDict",
]

from collections.abc import Buffer
from typing import Any

import msgspec


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
        for key, value in list(self.items()):
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
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'DotDict' object has no attribute '{key}'") from None

    def __setattr__(self, key: K, value: V) -> None:
        if isinstance(value, dict):
            self[key] = DotDict(value)  # type: ignore[arg-type]
        elif isinstance(value, list):
            self[key] = [  # type: ignore[arg-type]
                DotDict(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            self[key] = value

    def __delattr__(self, key: K) -> None:
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'DotDict' object has no attribute '{key}'") from None

    @classmethod
    def decode(cls, raw: Buffer | str) -> "DotDict[Any, Any]":
        """Decode JSON bytes or string directly into a :class:`DotDict`.

        This is a convenience for ``DotDict(msgspec.json.decode(raw, type=dict))``.
        """
        data: dict[str, Any] = msgspec.json.decode(raw, type=dict)
        return cls(data)

    def has(self, key: K) -> bool:
        """Return ``True`` if *key* is present."""
        return key in self

    def __repr__(self) -> str:
        return f"DotDict({super().__repr__()})"

    __str__ = __repr__
