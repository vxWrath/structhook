# structhook

Extra field info, computed fields, and hooks for `msgspec.Struct`.

```python
from structhook import BaseModel, field, serialize, deserialize, validate, computed_field

class User(BaseModel):
    name: str
    email: str
    role: str = "user"
    password_hash: str = field(exclude=True, default="")

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
>>> user = User.decode(b'{"name":"alice","email":" ALICE@EXAMPLE.COM "}')
>>> user
User(name='alice', email='alice@example.com', role='user', password_hash='')

>>> user.encode()
b'{"name":"ALICE","email":"alice@example.com","role":"user","display_name":"Alice"}'

>>> user.dump()
{'name': 'ALICE', 'email': 'alice@example.com', 'role': 'user', 'display_name': 'Alice'}

>>> user.dump(include=["name", "email"])
['ALICE', 'alice@example.com']

>>> user.dump(fire_hooks=False)
{'name': 'alice', 'email': 'alice@example.com', 'role': 'user', 'display_name': 'Alice'}
```

## Features

- **Lifecycle hooks** — `@serialize`, `@deserialize`, `@validate` decorators run per-field transforms during encode/decode.
- **Computed fields** — `@computed_field` for read-only derived values in serialized output.
- **Field exclusion** — `field(exclude=True)` keeps secrets out of `encode()` / `dump()`.
- **Controlled output** — `dump()` supports `include` filtering, `fire_hooks` toggle, JSON and Python modes.
- **Dict-like access** — `model["key"]` / `model["key"] = value`.
- **Fast path** — models without hooks, computed, or excluded fields use raw msgspec encode/decode with zero overhead.

## Install

```bash
pip install structhook
```

Requires Python ≥ 3.14 and msgspec ≥ 0.21.1.

## API

### `BaseModel`

Subclass of `msgspec.Struct` with `kw_only=True`, `dict=True`.

| Method | Description |
|--------|-------------|
| `encode() -> bytes` | Encode to JSON bytes (always fires serialize hooks). |
| `dump(mode, include, fire_hooks)` | Convert to plain dict (or JSON-roundtripped dict). |
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

## License

MIT
