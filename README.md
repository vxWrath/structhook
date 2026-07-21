# structhook

Extra field info, computed fields, and hooks for `msgspec.Struct` - plus a
`DotDict` type for working with arbitrary JSON without defining a schema.

## Quickstart

### HookStruct - schema-aware models with hooks

```python
from structhook import HookStruct, DotDict, field, serialize, deserialize, validate, computed_field

class User(HookStruct):
    name: str
    email: str
    role: str = "user"
    password_hash: str = field(exclude=True, default="")
    metadata: DotDict = field(default_factory=DotDict)

    @computed_field
    def display_name(self) -> str:
        return self.name.title()

    @deserialize("email")
    def _clean_email(cls, v: str) -> str:
        return v.strip().lower()

    @validate("role")
    def _check_role(cls, v: str) -> str:
        if v not in ("admin", "user", "guest"):
            raise ValueError(f"unknown role: {v}")
        return v

    @serialize("name")
    def _upper_name(self, v: str) -> str:
        return v.upper()
```

Deserialize and validate hooks fire during `decode()` / `convert()`:

```pycon
>>> user = User.decode(b'{"name":"alice","email":" ALICE@EXAMPLE.COM ","metadata":{"plan":"pro"}}')
>>> user
User(name='alice', email='alice@example.com', role='user', password_hash='', metadata=DotDict({'plan': 'pro'}))

>>> user.metadata.plan
'pro'

>>> user.encode()
b'{"name":"ALICE","email":"alice@example.com","role":"user","metadata":{"plan":"pro"},"display_name":"Alice"}'

>>> user.dump()
{'name': 'ALICE', 'email': 'alice@example.com', 'role': 'user', 'metadata': {'plan': 'pro'}, 'display_name': 'Alice'}

>>> user.dump(include=["name", "email"])
{'name': 'ALICE', 'email': 'alice@example.com'}

>>> user.to_positional(include=["name", "email"])
('ALICE', 'alice@example.com')

>>> user.dump(fire_hooks=False)
{'name': 'alice', 'email': 'alice@example.com', 'role': 'user', 'metadata': {'plan': 'pro'}, 'display_name': 'Alice'}
```

### DotDict

```pycon
>>> from structhook import DotDict

>>> d = DotDict.decode(b'{"user":{"name":"Alice","scores":[90,95]}}')
>>> d.user.name
'Alice'
>>> d.user.scores[0]
90

>>> d.new_field = {"nested": True}
>>> d.new_field.nested
True
```

Nested dicts and lists of dicts are recursively wrapped at construction time,
so you can chain dots arbitrarily deep.  Use it anywhere you'd reach for a
plain `dict` - API responses, config files, feature flags, etc.

`DotDict` is also a first-class field type in `HookStruct` models - arbitrary
JSON blobs get decoded to `DotDict` automatically (see above).

## Features

### HookStruct
- **Lifecycle hooks** - `@serialize`, `@deserialize`, `@validate` decorators run per-field transforms during encode/decode.
- **Computed fields** - `@computed_field` for read-only derived values in serialized output.
- **Field exclusion** - `field(exclude=True)` keeps secrets out of `encode()` / `dump()`.
- **Controlled output** - `dump()` supports `include` / `exclude` filtering, `fire_hooks` toggle, JSON and Python modes.
- **Dict-like access** - `model["key"]` / `model["key"] = value`.
- **msgspec codec hooks** - override `msgspec_enc_hook` / `msgspec_dec_hook` to teach msgspec about custom types.
- **Fast path** - models without hooks, computed, or excluded fields use raw msgspec encode/decode with zero overhead.

### DotDict
- **Dot-access** - `d.user.profile.email` instead of `d["user"]["profile"]["email"]`.
- **Recursive wrapping** - nested dicts and lists of dicts are wrapped eagerly so dots chain arbitrarily deep.
- **JSON decode** - `DotDict.decode(raw_bytes)` goes straight from JSON bytes to a DotDict.
- **HookStruct integration** - use `DotDict` as a field type and arbitrary JSON is decoded automatically.
- **Collision detection** - accessing a key that collides with a built-in `dict` method (e.g. `d.keys` when the data has a `"keys"` key) raises `AttributeError` with a clear message.

## Benchmarks

structhook is benchmarked against raw `msgspec.Struct` to measure the overhead of
each feature.  Models without hooks, computed fields, or excluded fields take the
**fast path** — they use msgspec's native encode/decode with only a thin wrapper.

| Operation | Scenario | ops/sec | vs msgspec |
|-----------|----------|---------|------------|
| **encode** | msgspec.Struct (baseline) | 6,578,363 | 1.00x |
| | HookStruct fast path | 5,382,363 | 0.82x |
| | + serialize, computed, excluded | 1,093,827 | 0.17x |
| **decode** | msgspec.Struct (baseline) | 3,774,404 | 1.00x |
| | HookStruct fast path | 3,346,922 | 0.89x |
| | + deserialize + validate hooks | 789,520 | 0.21x |
| **convert** | msgspec.Struct (baseline) | 5,107,083 | 1.00x |
| | HookStruct fast path | 3,506,785 | 0.69x |
| | + deserialize + validate hooks | 1,124,963 | 0.22x |
| **DotDict** | `msgspec.json.decode(raw, type=dict)` | 643,929 | 1.00x |
| | `DotDict.decode(raw)` | 208,297 | 0.32x |

> Run the benchmarks locally: `python benchmarks/bench.py`.  The fast path
> (no hooks, computed, or excluded fields) stays within ~20% of raw msgspec.
> Features like serialize hooks, computed fields, and excluded fields each
> add a proportional amount of Python work on top of msgspec's C
> implementation — you only pay for what you use.

## Install

```bash
pip install structhook
```

Requires Python ≥ 3.14 and msgspec ≥ 0.21.1.

## API

### `HookStruct`

Subclass of `msgspec.Struct` with `kw_only=True`, `dict=True`.

| Method | Description |
|--------|-------------|
| `encode() -> bytes` | Encode to JSON bytes (always fires serialize hooks). |
| `dump(mode, include, exclude, fire_hooks)` | Convert to plain dict (or JSON-roundtripped dict). |
| `to_positional(mode, include, exclude, fire_hooks, computed)` | Return a tuple of values in declaration order (ideal for SQL positional parameters). |
| `decode(raw) -> Self` | Decode JSON bytes/string into a model (fires deserialize + validate hooks). |
| `convert(data) -> Self` | Convert a dict-like object into a model (fires deserialize + validate hooks). |
| `copy(**changes) -> Self` | Shallow copy with field replacements. |

### `field(**options)`

Drop-in replacement for `msgspec.field` with two extra options:

| Option | Type | Description |
|--------|------|-------------|
| `exclude` | `bool` | Exclude from `encode()` / `dump()` output. |
| `extra` | `Any` | User-defined metadata (for code-gen, OpenAPI, etc.). |

### `@serialize(fields)`

Runs **after** computed/excluded processing, **before** JSON encoding.  
Signature: `(self, value) -> new_value`

### `@deserialize(fields)`

Runs on raw JSON dict **before** struct conversion, during `decode()` / `convert()`.  
Signature: `(cls, raw_value) -> new_value`

### `@validate(fields)`

Runs **after** struct conversion, during `decode()` / `convert()`. The value is already type-coerced.  
Signature: `(cls, value) -> new_value`

> **Warning:** Validate hooks mutate the model post-construction via `object.__setattr__` and are incompatible with `frozen=True`.

### `@computed_field`

Read-only property injected into `encode()` / `dump()` output but not stored in the underlying struct.

### `DotDict`

A `dict` subclass with attribute-style access.  Stands alone - no model
definition required.

```pycon
>>> from structhook import DotDict

>>> d = DotDict.decode(b'{"user":{"name":"Alice","scores":[90,95]}}')
>>> d.user.name
'Alice'
>>> d.user.scores[0]
90
```

| Member | Description |
|--------|-------------|
| `DotDict(...)` | Wrap a mapping or kwargs.  Nested dicts/lists are wrapped recursively. |
| `DotDict.decode(raw, *, dec_hook=None)` | Decode JSON bytes/str directly into a DotDict. |
| `d.key` | Attribute-style access.  Raises `AttributeError` on missing keys *and* on collision with built-in dict methods. |
| `d["key"]` | Standard bracket access. |
| `d.key = value` | Attribute-style assignment.  Dicts/lists-of-dicts are auto-wrapped. |
| `d.has(key)` | Return `True` if *key* is present. |

## License

MIT
