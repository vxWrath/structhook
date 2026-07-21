"""Tests for the structhook.model module."""

from typing import Any

import pytest
from msgspec import NODEFAULT

from structhook import (
    DotDict,
    Field,
    HookStruct,
    Stage,
    computed_field,
    field,
    post_load,
    pre_load,
    pre_unload,
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

    def test_dump_include_and_exclude_mutually_exclusive(self) -> None:
        s = Simple(name="Alice", age=30)
        with pytest.raises(ValueError, match="mutually exclusive"):
            s.dump(include=["name"], exclude=["age"])

    def test_dump_exclude(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s.dump(exclude=["age"]) == {"name": "Alice"}

    def test_getitem(self) -> None:
        s = Simple(name="Alice", age=30)
        assert s["name"] == "Alice"
        assert s["age"] == 30

    def test_setitem(self) -> None:
        s = Simple(name="Alice", age=30)
        s["age"] = 31
        assert s.age == 31

    def test_contains(self) -> None:
        s = Simple(name="Alice", age=30)
        assert "name" in s
        assert "age" in s
        assert "missing" not in s

    def test_len(self) -> None:
        s = Simple(name="Alice", age=30)
        assert len(s) == 2

    def test_iter(self) -> None:
        s = Simple(name="Alice", age=30)
        assert list(s) == ["name", "age"]

    def test_delitem_raises(self) -> None:
        s = Simple(name="Alice", age=30)
        with pytest.raises(TypeError, match="Cannot delete field"):
            del s["name"]

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
        f = Field(default=1, name="x", exclude=True, extra={"doc": "test"})
        r = repr(f)
        assert "default=1" in r
        assert "name='x'" in r
        assert "exclude=True" in r
        assert "extra={'doc': 'test'}" in r

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
# Pre-unload hooks
# ---------------------------------------------------------------------------


class WithPreUnload(HookStruct):
    name: str
    count: int = 0

    @pre_unload("name")
    def _upper_name(self, v: str) -> str:
        return v.upper()


class TestPreUnloadHooks:
    def test_encode_fires_hook(self) -> None:
        m = WithPreUnload(name="alice")
        assert m.encode() == b'{"name":"ALICE","count":0}'

    def test_dump_fires_hook_by_default(self) -> None:
        m = WithPreUnload(name="alice")
        assert m.dump()["name"] == "ALICE"

    def test_dump_fire_hooks_false(self) -> None:
        m = WithPreUnload(name="alice")
        assert m.dump(fire_hooks=False)["name"] == "alice"

    def test_dump_json_fire_hooks_false(self) -> None:
        m = WithPreUnload(name="alice")
        assert m.dump(mode="json", fire_hooks=False)["name"] == "alice"


class WithMultiFieldPreUnload(HookStruct):
    a: str = ""
    b: str = ""

    @pre_unload(["a", "b"])
    def _upper(self, v: str) -> str:
        return v.upper()


class TestMultiFieldPreUnload:
    def test_both_fields(self) -> None:
        m = WithMultiFieldPreUnload(a="hello", b="world")
        data = m.dump()
        assert data["a"] == "HELLO"
        assert data["b"] == "WORLD"


# ---------------------------------------------------------------------------
# Pre-load hooks
# ---------------------------------------------------------------------------


class WithPreLoad(HookStruct):
    name: str
    age: int = 0

    @pre_load("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        return v.strip().title()


class TestPreLoadHooks:
    def test_decode_applies(self) -> None:
        m = WithPreLoad.decode(b'{"name":"  alice  "}')
        assert m.name == "Alice"

    def test_convert_applies(self) -> None:
        m = WithPreLoad.convert({"name": "  bob  "})
        assert m.name == "Bob"

    def test_requires_classmethod(self) -> None:
        """pre_load raises TypeError if @classmethod is missing."""
        with pytest.raises(TypeError, match="pre_load requires @classmethod"):

            class _Bad(HookStruct):
                name: str = ""

                @pre_load("name")  # no @classmethod below
                def _clean(cls, v: str) -> str:
                    return v.strip()


# ---------------------------------------------------------------------------
# Post-load hooks
# ---------------------------------------------------------------------------


class WithPostLoad(HookStruct):
    score: int

    @post_load("score")
    def _check_score(self, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError(f"score {v} out of range 0-100")
        return v


class TestPostLoadHooks:
    def test_valid(self) -> None:
        m = WithPostLoad(score=50)
        assert m.score == 50

    def test_invalid(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            WithPostLoad.convert({"score": 150})

    def test_decode_applies(self) -> None:
        m = WithPostLoad.decode(b'{"score":75}')
        assert m.score == 75


class ChainedPostLoad(HookStruct):
    x: int = 0

    @post_load("x")
    def _double(self, v: int) -> int:
        return v * 2

    @post_load("x")
    def _add_one(self, v: int) -> int:
        return v + 1


class TestChainedPostLoad:
    def test_order(self) -> None:
        m = ChainedPostLoad.convert({"x": 5})
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

    def test_frozen_with_post_load_raises_at_class_creation(self) -> None:
        with pytest.raises(TypeError, match="frozen"):

            class _FrozenBad(HookStruct, frozen=True):
                x: int

                @post_load("x")
                def _val(self, v: int) -> int:
                    return v


# ---------------------------------------------------------------------------
# dump() with fire_hooks
# ---------------------------------------------------------------------------


class WithPreUnloadAndComputed(HookStruct):
    name: str
    secret: str = field(exclude=True, default="shh")

    @computed_field
    def loud(self) -> str:
        return self.name.upper()

    @pre_unload("name")
    def _title(self, v: str) -> str:
        return v.title()


class TestDumpFireHooks:
    def test_default(self) -> None:
        m = WithPreUnloadAndComputed(name="alice")
        data = m.dump()
        assert data["name"] == "Alice"  # hook fired
        assert data["loud"] == "ALICE"  # computed always present
        assert "secret" not in data

    def test_no_hooks(self) -> None:
        m = WithPreUnloadAndComputed(name="alice")
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
# Inherited hooks and computed fields
# ---------------------------------------------------------------------------


class ParentWithComputed(HookStruct):
    name: str

    @computed_field
    def loud(self) -> str:
        return self.name.upper()


class ChildOfComputed(ParentWithComputed):
    age: int = 0


class TestInheritedComputed:
    def test_child_inherits_computed(self) -> None:
        c = ChildOfComputed(name="bob")
        assert "loud" in c.dump()
        assert c.dump()["loud"] == "BOB"

    def test_child_computed_fields_attr(self) -> None:
        assert "loud" in ChildOfComputed.__computed_fields__

    def test_grandchild_inherits_computed(self) -> None:
        class GrandChild(ChildOfComputed):
            extra: str = ""

        gc = GrandChild(name="eve")
        assert gc.dump()["loud"] == "EVE"


class ParentWithPreUnload(HookStruct):
    name: str

    @pre_unload("name")
    def _upper(self, v: str) -> str:
        return v.upper()


class ChildOfPreUnload(ParentWithPreUnload):
    pass


class TestInheritedPreUnload:
    def test_child_encode_fires_parent_hook(self) -> None:
        c = ChildOfPreUnload(name="alice")
        assert c.encode() == b'{"name":"ALICE"}'

    def test_child_dump_fires_parent_hook(self) -> None:
        c = ChildOfPreUnload(name="alice")
        assert c.dump()["name"] == "ALICE"

    def test_child_dump_no_hooks_still_works(self) -> None:
        c = ChildOfPreUnload(name="alice")
        assert c.dump(fire_hooks=False)["name"] == "alice"


class ParentWithPreLoad(HookStruct):
    name: str

    @pre_load("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        return v.strip().title()


class ChildOfPreLoad(ParentWithPreLoad):
    pass


class TestInheritedPreLoad:
    def test_child_decode_applies_parent_hook(self) -> None:
        c = ChildOfPreLoad.decode(b'{"name":"  alice  "}')
        assert c.name == "Alice"

    def test_child_convert_applies_parent_hook(self) -> None:
        c = ChildOfPreLoad.convert({"name": "  bob  "})
        assert c.name == "Bob"


class ParentWithPostLoad(HookStruct):
    score: int

    @post_load("score")
    def _clamp(self, v: int) -> int:
        return max(0, min(v, 100))


class ChildOfPostLoad(ParentWithPostLoad):
    pass


class TestInheritedPostLoad:
    def test_child_decode_applies_parent_hook(self) -> None:
        c = ChildOfPostLoad.convert({"score": 200})
        assert c.score == 100

    def test_child_convert_applies_parent_hook(self) -> None:
        c = ChildOfPostLoad.convert({"score": -10})
        assert c.score == 0


class HookOrderParent(HookStruct):
    x: int = 0

    @post_load("x")
    def _parent_hook(self, v: int) -> int:
        return v * 2


class HookOrderChild(HookOrderParent):
    @post_load("x")
    def _child_hook(self, v: int) -> int:
        return v + 1


class TestHookOrderingInheritance:
    def test_parent_runs_before_child(self) -> None:
        m = HookOrderChild.convert({"x": 5})
        assert m.x == 11  # (5 * 2) + 1


class ParentFieldMeta(HookStruct):
    secret: str = field(exclude=True, default="shh")
    tagged: str = field(extra={"doc": "The tag"}, default="")


class ChildFieldMeta(ParentFieldMeta):
    pass


class TestInheritedFieldMeta:
    def test_exclude_inherited(self) -> None:
        assert ChildFieldMeta.__fields__["secret"].exclude is True
        c = ChildFieldMeta(secret="xyz")
        assert "secret" not in c.dump()

    def test_extra_inherited(self) -> None:
        assert ChildFieldMeta.__fields__["tagged"].extra == {"doc": "The tag"}


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

    def test_post_load_transform(self) -> None:
        """Post-load hooks can transform values."""

        class Transform(HookStruct):
            x: int

            @post_load("x")
            def _clamp(self, v: int) -> int:
                return max(0, min(v, 100))

        m = Transform.convert({"x": 200})
        assert m.x == 100

    def test_pre_load_before_post_load(self) -> None:
        """pre_load hooks run before post_load hooks."""

        class Order(HookStruct):
            value: str = ""

            @pre_load("value")
            @classmethod
            def _strip(cls, v: str) -> str:
                return v.strip()

            @post_load("value")
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
        assert Stage.PRE_UNLOAD == "pre_unload"
        assert Stage.PRE_LOAD == "pre_load"
        assert Stage.POST_LOAD == "post_load"

    def test_extra_metadata_preserved(self) -> None:
        class WithExtra(HookStruct):
            name: str = field(extra={"doc": "The name"})

        assert WithExtra.__fields__["name"].extra == {"doc": "The name"}


# ---------------------------------------------------------------------------
# to_positional
# ---------------------------------------------------------------------------


class WithComputedForPositional(HookStruct):
    first: str
    last: str

    @computed_field
    def full_name(self) -> str:
        return f"{self.first} {self.last}"


class TestToPositional:
    def test_basic(self) -> None:
        m = WithComputedForPositional(first="Alice", last="Smith")
        assert m.to_positional() == ("Alice", "Smith")

    def test_excludes_computed_by_default(self) -> None:
        m = WithComputedForPositional(first="Alice", last="Smith")
        assert "full_name" not in m.to_positional()
        assert len(m.to_positional()) == 2

    def test_include_computed(self) -> None:
        m = WithComputedForPositional(first="Alice", last="Smith")
        result = m.to_positional(computed=True)
        assert result == ("Alice", "Smith", "Alice Smith")

    def test_include_controls_order(self) -> None:
        m = WithComputedForPositional(first="Alice", last="Smith")
        result = m.to_positional(include=["last", "first"])
        assert result == ("Smith", "Alice")

    def test_with_hooks(self) -> None:
        class M(HookStruct):
            name: str

            @pre_unload("name")
            def _upper(self, v: str) -> str:
                return v.upper()

        m = M(name="alice")
        assert m.to_positional() == ("ALICE",)
        assert m.to_positional(fire_hooks=False) == ("alice",)


# ---------------------------------------------------------------------------
# msgspec_enc_hook / msgspec_dec_hook overrides
# ---------------------------------------------------------------------------


class CustomType:
    """A simple wrapper type used in hook override tests."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, CustomType):
            return self.value == other.value
        return NotImplemented

    def __repr__(self) -> str:
        return f"CustomType({self.value!r})"


class TestMsgspecEncHookOverride:
    """Test overriding ``msgspec_enc_hook`` on a HookStruct subclass."""

    def test_custom_type_encoded(self) -> None:
        class WithCustomEnc(HookStruct):
            name: str
            data: CustomType = field(default_factory=lambda: CustomType("default"))

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                if isinstance(obj, CustomType):
                    return {"__custom__": obj.value}
                return HookStruct.msgspec_enc_hook(obj)

        m = WithCustomEnc(name="test", data=CustomType("hello"))
        encoded = m.encode()
        assert b'"__custom__"' in encoded
        assert b'"hello"' in encoded

    def test_fallback_to_parent(self) -> None:
        """Child delegates to Parent's enc_hook for types it doesn't handle."""

        class Parent(HookStruct):
            value: str = ""

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                if isinstance(obj, CustomType):
                    return {"__custom__": obj.value}
                return HookStruct.msgspec_enc_hook(obj)

        class Child(Parent):
            data: CustomType = field(default_factory=lambda: CustomType("child_val"))

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                # Child doesn't handle CustomType - delegates to Parent
                return Parent.msgspec_enc_hook(obj)

        m = Child(data=CustomType("hello"))
        encoded = m.encode()
        assert b'"__custom__"' in encoded  # Parent's hook handled it
        assert b'"hello"' in encoded

    def test_dump_json_mode_uses_class_encoder(self) -> None:
        class WithJsonRoundtrip(HookStruct):
            value: str

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                if isinstance(obj, CustomType):
                    return obj.value
                return HookStruct.msgspec_enc_hook(obj)

        m = WithJsonRoundtrip(value="hello")
        data = m.dump(mode="json")
        assert data == {"value": "hello"}


class TestMsgspecDecHookOverride:
    """Test overriding ``msgspec_dec_hook`` on a HookStruct subclass."""

    def test_custom_type_decoded(self) -> None:
        class WithCustomDec(HookStruct):
            name: str
            data: CustomType = field(default_factory=lambda: CustomType("default"))

            @staticmethod
            def msgspec_dec_hook(typ: type[Any], obj: Any) -> Any:
                if typ is CustomType:
                    return CustomType(obj["__custom__"])
                return HookStruct.msgspec_dec_hook(typ, obj)

        m = WithCustomDec.decode(b'{"name":"test","data":{"__custom__":"hello"}}')
        assert m.name == "test"
        assert isinstance(m.data, CustomType)
        assert m.data.value == "hello"

    def test_convert_applies(self) -> None:
        class WithCustomDec(HookStruct):
            name: str
            data: CustomType = field(default_factory=lambda: CustomType("default"))

            @staticmethod
            def msgspec_dec_hook(typ: type[Any], obj: Any) -> Any:
                if typ is CustomType:
                    return CustomType(obj["__custom__"])
                return HookStruct.msgspec_dec_hook(typ, obj)

        m = WithCustomDec.convert({"name": "test", "data": {"__custom__": "world"}})
        assert isinstance(m.data, CustomType)
        assert m.data.value == "world"

    def test_fallback_to_parent(self) -> None:
        class Parent(HookStruct):
            name: str

            @staticmethod
            def msgspec_dec_hook(typ: type[Any], obj: Any) -> Any:
                return HookStruct.msgspec_dec_hook(typ, obj)

        class Child(Parent):
            # No override - inherits Parent's hook.  Should still decode
            # DotDict fields correctly via the base implementation.
            config: DotDict = field(default_factory=DotDict)

        m = Child.decode(b'{"name":"x","config":{"key":"val"}}')
        assert isinstance(m.config, DotDict)
        assert m.config.key == "val"


class TestMsgspecHooksRoundtrip:
    """Test both hooks together for full encode-decode roundtrip."""

    def test_full_roundtrip(self) -> None:
        class WithBothHooks(HookStruct):
            name: str
            data: CustomType = field(default_factory=lambda: CustomType("default"))

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                if isinstance(obj, CustomType):
                    return {"__custom__": obj.value}
                return HookStruct.msgspec_enc_hook(obj)

            @staticmethod
            def msgspec_dec_hook(typ: type[Any], obj: Any) -> Any:
                if typ is CustomType:
                    return CustomType(obj["__custom__"])
                return HookStruct.msgspec_dec_hook(typ, obj)

        original = WithBothHooks(name="roundtrip", data=CustomType("test_value"))
        decoded = WithBothHooks.decode(original.encode())
        assert decoded == original  # uses CustomType.__eq__

    def test_subclasses_dont_interfere(self) -> None:
        """Different subclasses with different hooks should not conflict."""

        class ModelA(HookStruct):
            value: str = ""

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                if isinstance(obj, CustomType):
                    return "from_a"
                return HookStruct.msgspec_enc_hook(obj)

        class ModelB(HookStruct):
            value: str = ""

            @staticmethod
            def msgspec_enc_hook(obj: Any) -> Any:
                if isinstance(obj, CustomType):
                    return "from_b"
                return HookStruct.msgspec_enc_hook(obj)

        a = ModelA(value="x")
        b = ModelB(value="x")
        assert a.encode() == b'{"value":"x"}'  # ModelA's encoder
        assert b.encode() == b'{"value":"x"}'  # ModelB's encoder

    def test_default_hook_raises_on_unknown_type(self) -> None:
        """The base HookStruct hook should raise TypeError on unknown types."""

        class DefaultModel(HookStruct):
            name: str

        # Encode should work normally
        m = DefaultModel(name="test")
        assert m.encode() == b'{"name":"test"}'

        # But encoding a CustomType directly (without hook override) should raise
        with pytest.raises(TypeError, match="Cannot encode"):
            HookStruct.msgspec_enc_hook(CustomType("x"))
