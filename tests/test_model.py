"""Tests for the structhook.model module."""

from typing import Any

import pytest
from msgspec import NODEFAULT

from structhook import (
    Field,
    HookStruct,
    Stage,
    computed_field,
    deserialize,
    field,
    serialize,
    validate,
)

# ---------------------------------------------------------------------------
# Basic model lifecycle
# ---------------------------------------------------------------------------


class Simple(HookStruct):
    name: str
    age: int = 0


class TestBasicModel:
    def test_create(self) -> None:
        s = Simple(name="Alice")
        assert s.name == "Alice"
        assert s.age == 0

    def test_encode(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s.encode() == b'{"name":"Alice","age":30}'

    def test_decode(self) -> None:
        s = Simple.decode(b'{"name":"Bob","age":25}')
        assert s.name == "Bob"
        assert s.age == 25

    def test_decode_str(self) -> None:
        s = Simple.decode('{"name":"Bob","age":25}')
        assert s.name == "Bob"

    def test_convert(self) -> None:
        s = Simple.convert({"name": "Charlie", "age": 40})
        assert s.name == "Charlie"
        assert s.age == 40

    def test_roundtrip(self) -> None:
        s = Simple(name="Diana", age=50)
        assert Simple.decode(s.encode()) == s

    def test_copy(self) -> None:
        s = Simple(name="Eve", age=60)
        s2 = s.copy(age=61)
        assert s2.name == "Eve"
        assert s2.age == 61
        assert s.age == 60  # original unchanged

    def test_dump_python(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s.dump() == {"name": "Alice", "age": 30}

    def test_dump_json(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s.dump(mode="json") == {"name": "Alice", "age": 30}

    def test_dump_include(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s.dump(include=["name"]) == {"name": "Alice"}

    def test_dump_include_missing(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s.dump(include=["name", "missing"]) == {"name": "Alice"}

    def test_getitem(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s["name"] == "Alice"
        assert s["age"] == 30

    def test_setitem(self) -> None:
        s = Simple(name="Alice", age=30)
        s["age"] = 31
        assert s.age == 31

    def test_repr(self) -> None:
        s = Simple(name="Alice", age=30)
        r = repr(s)
        assert "Simple" in r
        assert "Alice" in r


# ---------------------------------------------------------------------------
# Field descriptor
# ---------------------------------------------------------------------------


class TestField:
    def test_default_value(self) -> None:
        f = Field(default=42)
        assert f.default == 42
        assert f.default_factory is NODEFAULT
        assert not f.is_required

    def test_default_factory(self) -> None:
        f = Field(default_factory=list)
        assert f.default_factory is list
        assert f.default is NODEFAULT
        assert not f.is_required

    def test_required(self) -> None:
        f = Field()
        assert f.is_required

    def test_exclude(self) -> None:
        f = Field(exclude=True)
        assert f.exclude

    def test_extra(self) -> None:
        f = Field(extra={"doc": "hello"})
        assert f.extra == {"doc": "hello"}

    def test_name_override(self) -> None:
        f = Field(name="custom_name")
        assert f.name == "custom_name"

    def test_repr(self) -> None:
        f = Field(default=1, name="x", exclude=True)
        r = repr(f)
        assert "default=1" in r
        assert "name='x'" in r
        assert "exclude=True" in r

    def test_cannot_set_both_default_and_factory(self) -> None:
        with pytest.raises(ValueError, match="Cannot specify both"):
            field(default=1, default_factory=list)


class ModelWithFieldOptions(HookStruct):
    required: str
    optional: str = "fallback"
    factory_list: list[int] = field(default_factory=list)
    renamed: str = field(name="alias")


class TestFieldOptions:
    def test_required_missing(self) -> None:
        with pytest.raises(TypeError, match="Missing required"):
            ModelWithFieldOptions()  # type: ignore

    def test_optional_default(self) -> None:
        m = ModelWithFieldOptions(required="x", renamed="val")
        assert m.optional == "fallback"

    def test_factory(self) -> None:
        m1 = ModelWithFieldOptions(required="x", renamed="val")
        m2 = ModelWithFieldOptions(required="x", renamed="val")
        assert m1.factory_list is not m2.factory_list  # distinct instances

    def test_name_override_encode(self) -> None:
        m = ModelWithFieldOptions(required="x", renamed="value")
        encoded = m.encode()
        assert b"alias" in encoded
        assert b"renamed" not in encoded

    def test_name_override_decode(self) -> None:
        m = ModelWithFieldOptions.decode(b'{"required":"x","alias":"value"}')
        assert m.renamed == "value"


# ---------------------------------------------------------------------------
# Excluded fields
# ---------------------------------------------------------------------------


class WithExcluded(HookStruct):
    public: str
    secret: str = field(exclude=True)


class TestExcludedFields:
    def test_encode_excludes(self) -> None:
        m = WithExcluded(public="hello", secret="shh")
        encoded = m.encode()
        assert b"secret" not in encoded
        assert b"public" in encoded

    def test_dump_excludes(self) -> None:
        m = WithExcluded(public="hello", secret="shh")
        data = m.dump()
        assert "public" in data
        assert "secret" not in data

    def test_decode_includes(self) -> None:
        m = WithExcluded.decode(b'{"public":"hello","secret":"shh"}')
        assert m.secret == "shh"

    def test_access_still_works(self) -> None:
        m = WithExcluded(public="hello", secret="shh")
        assert m.secret == "shh"


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------


class WithComputed(HookStruct):
    first: str
    last: str

    @computed_field
    def full_name(self) -> str:
        return f"{self.first} {self.last}"


class TestComputedFields:
    def test_dump_includes(self) -> None:
        m = WithComputed(first="John", last="Doe")
        data = m.dump()
        assert data == {"first": "John", "last": "Doe", "full_name": "John Doe"}

    def test_encode_includes(self) -> None:
        m = WithComputed(first="John", last="Doe")
        assert b"full_name" in m.encode()

    def test_cannot_set_via_init(self) -> None:
        with pytest.raises(TypeError):
            WithComputed(first="John", last="Doe", full_name="bad")  # type: ignore

    def test_cannot_set_via_copy(self) -> None:
        m = WithComputed(first="John", last="Doe")
        with pytest.raises(TypeError, match="computed field"):
            m.copy(full_name="bad")

    def test_after_copy_recomputed(self) -> None:
        m = WithComputed(first="John", last="Doe")
        m2 = m.copy(first="Jane")
        assert m2.full_name == "Jane Doe"


# ---------------------------------------------------------------------------
# Serialize hooks
# ---------------------------------------------------------------------------


class WithSerialize(HookStruct):
    name: str
    count: int = 0

    @serialize("name")
    def _upper_name(self, v: str) -> str:
        return v.upper()


class TestSerializeHooks:
    def test_encode_fires_hook(self) -> None:
        m = WithSerialize(name="alice")
        assert m.encode() == b'{"name":"ALICE","count":0}'

    def test_dump_fires_hook_by_default(self) -> None:
        m = WithSerialize(name="alice")
        assert m.dump()["name"] == "ALICE"

    def test_dump_fire_hooks_false(self) -> None:
        m = WithSerialize(name="alice")
        assert m.dump(fire_hooks=False)["name"] == "alice"

    def test_dump_json_fire_hooks_false(self) -> None:
        m = WithSerialize(name="alice")
        assert m.dump(mode="json", fire_hooks=False)["name"] == "alice"


class WithMultiFieldSerialize(HookStruct):
    a: str = ""
    b: str = ""

    @serialize(["a", "b"])
    def _upper(self, v: str) -> str:
        return v.upper()


class TestMultiFieldSerialize:
    def test_both_fields(self) -> None:
        m = WithMultiFieldSerialize(a="hello", b="world")
        data = m.dump()
        assert data["a"] == "HELLO"
        assert data["b"] == "WORLD"


# ---------------------------------------------------------------------------
# Deserialize hooks
# ---------------------------------------------------------------------------


class WithDeserialize(HookStruct):
    name: str
    age: int = 0

    @deserialize("name")
    def _clean_name(self, v: str) -> str:
        return v.strip().title()


class TestDeserializeHooks:
    def test_decode_applies(self) -> None:
        m = WithDeserialize.decode(b'{"name":"  alice  "}')
        assert m.name == "Alice"

    def test_convert_applies(self) -> None:
        m = WithDeserialize.convert({"name": "  bob  "})
        assert m.name == "Bob"


# ---------------------------------------------------------------------------
# Validate hooks
# ---------------------------------------------------------------------------


class WithValidate(HookStruct):
    score: int

    @validate("score")
    def _check_score(self, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError(f"score {v} out of range 0-100")
        return v


class TestValidateHooks:
    def test_valid(self) -> None:
        m = WithValidate(score=50)
        assert m.score == 50

    def test_invalid(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            WithValidate.convert({"score": 150})

    def test_decode_applies(self) -> None:
        m = WithValidate.decode(b'{"score":75}')
        assert m.score == 75


class ChainedValidate(HookStruct):
    x: int = 0

    @validate("x")
    def _double(self, v: int) -> int:
        return v * 2

    @validate("x")
    def _add_one(self, v: int) -> int:
        return v + 1


class TestChainedValidate:
    def test_order(self) -> None:
        m = ChainedValidate.convert({"x": 5})
        assert m.x == 11  # (5 * 2) + 1


# ---------------------------------------------------------------------------
# Frozen models
# ---------------------------------------------------------------------------


class TestFrozen:
    def test_frozen_without_hooks_works(self) -> None:
        class FrozenOk(HookStruct, frozen=True):
            x: int

        m = FrozenOk(x=1)
        assert m.x == 1

    def test_frozen_with_validate_raises_at_class_creation(self) -> None:
        with pytest.raises(TypeError, match="frozen"):

            class _FrozenBad(HookStruct, frozen=True):
                x: int

                @validate("x")
                def _val(self, v: int) -> int:
                    return v


# ---------------------------------------------------------------------------
# dump() with fire_hooks
# ---------------------------------------------------------------------------


class WithSerializeAndComputed(HookStruct):
    name: str
    secret: str = field(exclude=True, default="shh")

    @computed_field
    def loud(self) -> str:
        return self.name.upper()

    @serialize("name")
    def _title(self, v: str) -> str:
        return v.title()


class TestDumpFireHooks:
    def test_default(self) -> None:
        m = WithSerializeAndComputed(name="alice")
        data = m.dump()
        assert data["name"] == "Alice"  # hook fired
        assert data["loud"] == "ALICE"  # computed always present
        assert "secret" not in data

    def test_no_hooks(self) -> None:
        m = WithSerializeAndComputed(name="alice")
        data = m.dump(fire_hooks=False)
        assert data["name"] == "alice"  # raw value
        assert data["loud"] == "ALICE"  # computed still works
        assert "secret" not in data


# ---------------------------------------------------------------------------
# DictLike protocol
# ---------------------------------------------------------------------------


class CustomDictLike:
    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d

    def keys(self) -> Any:
        return self._d.keys()

    def __getitem__(self, key: str) -> Any:
        return self._d[key]


class TestDictLike:
    def test_custom_dictlike(self) -> None:
        c = CustomDictLike({"name": "Alice", "age": 30})
        s = Simple.convert(c)
        assert s.name == "Alice"


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class Parent(HookStruct):
    name: str


class Child(Parent):
    age: int = 0

    @computed_field
    def display(self) -> str:
        return f"{self.name} ({self.age})"


class TestInheritance:
    def test_inherits_fields(self) -> None:
        c = Child(name="Alice", age=30)
        assert c.name == "Alice"
        assert c.age == 30

    def test_inherits_methods(self) -> None:
        c = Child(name="Alice", age=30)
        data = c.dump()
        assert data["display"] == "Alice (30)"

    def test_encode_decode_roundtrip(self) -> None:
        c = Child(name="Bob", age=25)
        assert Child.decode(c.encode()) == c


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_model(self) -> None:
        class Empty(HookStruct):
            pass

        m = Empty()
        assert m.encode() == b"{}"
        assert m.dump() == {}

    def test_nested_models(self) -> None:
        class Inner(HookStruct):
            x: int

        class Outer(HookStruct):
            inner: Inner

        o = Outer(inner=Inner(x=1))
        encoded = o.encode()
        assert b'"x":1' in encoded
        decoded = Outer.decode(encoded)
        assert decoded.inner.x == 1

    def test_include_empty(self) -> None:
        s = Simple(name="Alice")
        assert s.dump(include=[]) == {}

    def test_field_repr(self) -> None:
        """Field.__repr__ should not raise."""
        f = Field()
        assert isinstance(repr(f), str)

    def test_validate_transform(self) -> None:
        """Validate hooks can transform values."""

        class Transform(HookStruct):
            x: int

            @validate("x")
            def _clamp(self, v: int) -> int:
                return max(0, min(v, 100))

        m = Transform.convert({"x": 200})
        assert m.x == 100

    def test_deserialize_before_validate(self) -> None:
        """Deserialize hooks run before validate hooks."""

        class Order(HookStruct):
            value: str = ""

            @deserialize("value")
            def _strip(self, v: str) -> str:
                return v.strip()

            @validate("value")
            def _check_not_empty(self, v: str) -> str:
                if not v:
                    raise ValueError("empty after strip")
                return v

        # Should work: whitespace stripped → "x"
        m = Order.decode(b'{"value":"  x  "}')
        assert m.value == "x"

        # Should fail: whitespace stripped → ""
        with pytest.raises(ValueError, match="empty after strip"):
            Order.decode(b'{"value":"   "}')

    def test_stage_enum_values(self) -> None:
        assert Stage.SERIALIZE == "serialize"
        assert Stage.DESERIALIZE == "deserialize"
        assert Stage.VALIDATE == "validate"

    def test_extra_metadata_preserved(self) -> None:
        class WithExtra(HookStruct):
            name: str = field(extra={"doc": "The name"})

        assert WithExtra.__fields__["name"].extra == {"doc": "The name"}
