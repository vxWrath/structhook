"""Tests for the structhook.dotdict module."""

import pytest

from structhook import DotDict, HookStruct

# ---------------------------------------------------------------------------
# Basic dot access
# ---------------------------------------------------------------------------


class TestBasicAccess:
    def test_getattr(self) -> None:
        d = DotDict(name="Alice", age=30)
        assert d.name == "Alice"
        assert d.age == 30

    def test_getattr_nested(self) -> None:
        d = DotDict({"user": {"name": "Alice"}})
        assert d.user.name == "Alice"

    def test_getattr_missing_raises_attribute_error(self) -> None:
        d = DotDict()
        with pytest.raises(AttributeError, match="'DotDict' object has no attribute 'missing'"):
            _ = d.missing

    def test_getitem(self) -> None:
        d = DotDict(name="Alice", age=30)
        assert d["name"] == "Alice"
        assert d["age"] == 30

    def test_getitem_missing_raises_key_error(self) -> None:
        d = DotDict()
        with pytest.raises(KeyError):
            _ = d["missing"]

    def test_setattr(self) -> None:
        d = DotDict()
        d.new_key = "value"
        assert d.new_key == "value"
        assert d["new_key"] == "value"

    def test_setattr_wraps_dict(self) -> None:
        d = DotDict()
        d.nested = {"a": 1}
        assert isinstance(d.nested, DotDict)
        assert d.nested.a == 1

    def test_setitem(self) -> None:
        d = DotDict()
        d["key"] = "value"
        assert d.key == "value"

    def test_setitem_wraps_dict(self) -> None:
        d = DotDict()
        d["nested"] = {"a": 1}
        assert isinstance(d["nested"], DotDict)
        assert d["nested"].a == 1

    def test_delattr(self) -> None:
        d = DotDict(name="Alice")
        del d.name
        with pytest.raises(AttributeError):
            _ = d.name

    def test_delattr_missing_raises_attribute_error(self) -> None:
        d = DotDict()
        with pytest.raises(AttributeError, match="'DotDict' object has no attribute 'missing'"):
            del d.missing

    def test_has(self) -> None:
        d = DotDict(name="Alice")
        assert d.has("name")
        assert not d.has("missing")

    def test_repr(self) -> None:
        d = DotDict(name="Alice")
        r = repr(d)
        assert r.startswith("DotDict(")
        assert "Alice" in r

    def test_str(self) -> None:
        d = DotDict(name="Alice")
        assert str(d) == repr(d)


# ---------------------------------------------------------------------------
# Nested wrapping (eager at init)
# ---------------------------------------------------------------------------


class TestNestedWrapping:
    def test_nested_dict_wrapped(self) -> None:
        d = DotDict({"a": {"b": {"c": 1}}})
        assert isinstance(d.a, DotDict)
        assert isinstance(d.a.b, DotDict)
        assert d.a.b.c == 1

    def test_list_of_dicts_wrapped(self) -> None:
        d = DotDict({"entries": [{"name": "a"}, {"name": "b"}]})
        assert isinstance(d.entries, list)
        assert isinstance(d.entries[0], DotDict)
        assert d.entries[0].name == "a"
        assert d.entries[1].name == "b"

    def test_nested_list_of_dicts_wrapped(self) -> None:
        d = DotDict({"users": [{"profile": {"email": "a@b.com"}}]})
        assert isinstance(d.users[0], DotDict)
        assert isinstance(d.users[0].profile, DotDict)
        assert d.users[0].profile.email == "a@b.com"

    def test_already_dotdict_preserved(self) -> None:
        inner = DotDict(x=1)
        d = DotDict({"a": inner})
        assert d.a is inner  # not re-wrapped

    def test_kwargs_nested(self) -> None:
        d = DotDict(a={"b": 1})
        assert d.a.b == 1

    def test_empty(self) -> None:
        d = DotDict()
        assert len(d) == 0


# ---------------------------------------------------------------------------
# Eager vs lazy: __getitem__ does not mutate
# ---------------------------------------------------------------------------


class TestGetItemNoMutation:
    def test_getitem_returns_already_wrapped(self) -> None:
        d = DotDict({"a": {"b": 1}})
        result1 = d["a"]
        result2 = d["a"]
        assert result1 is result2  # same object, no re-wrapping on each access


# ---------------------------------------------------------------------------
# decode() classmethod
# ---------------------------------------------------------------------------


class TestDecode:
    def test_decode_bytes(self) -> None:
        d = DotDict.decode(b'{"a": 1, "b": {"c": 2}}')
        assert d.a == 1
        assert d.b.c == 2

    def test_decode_string(self) -> None:
        d = DotDict.decode('{"x": [1, 2, 3]}')
        assert d.x == [1, 2, 3]

    def test_decode_nested_list(self) -> None:
        d = DotDict.decode(b'{"entries": [{"id": 1}, {"id": 2}]}')
        assert d.entries[0].id == 1
        assert d.entries[1].id == 2


# ---------------------------------------------------------------------------
# Integration with HookStruct encode/decode hooks
# ---------------------------------------------------------------------------


class TestHookStructIntegration:
    def test_dotdict_as_field_decodes(self) -> None:
        """DotDict typed fields should decode via dec_hook."""

        class WithDotDict(HookStruct):
            metadata: DotDict

        m = WithDotDict.decode(b'{"metadata": {"key": "value", "nested": {"a": 1}}}')
        assert isinstance(m.metadata, DotDict)
        assert m.metadata.key == "value"
        assert m.metadata.nested.a == 1

    def test_dotdict_in_list_field(self) -> None:
        class WithDotDictList(HookStruct):
            items: list[DotDict]

        m = WithDotDictList.decode(b'{"items": [{"a": 1}, {"b": 2}]}')
        assert isinstance(m.items[0], DotDict)
        assert m.items[0].a == 1
        assert m.items[1].b == 2

    def test_dotdict_encodes_to_plain_dict(self) -> None:
        class WithDotDict(HookStruct):
            metadata: DotDict

        m = WithDotDict(metadata=DotDict(key="value"))
        encoded = m.encode()
        assert b'"metadata":{"key":"value"}' in encoded

    def test_dotdict_roundtrip(self) -> None:
        class WithDotDict(HookStruct):
            metadata: DotDict

        original = WithDotDict(metadata=DotDict(key="value", nested=DotDict(a=1)))
        decoded = WithDotDict.decode(original.encode())
        assert decoded.metadata.key == "value"
        assert decoded.metadata.nested.a == 1
        assert isinstance(decoded.metadata, DotDict)
        assert isinstance(decoded.metadata.nested, DotDict)

    def test_dotdict_dump(self) -> None:
        class WithDotDict(HookStruct):
            metadata: DotDict

        m = WithDotDict(metadata=DotDict(key="value"))
        data = m.dump()
        assert data == {"metadata": {"key": "value"}}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_dict_method_name_key_raises_on_collision(self) -> None:
        """Keys that collide with dict methods raise AttributeError on dot access."""
        d = DotDict({"keys": "secret", "items": [1, 2]})
        # dot access raises because the keys collide with dict methods
        with pytest.raises(AttributeError, match="collides with a built-in dict method"):
            _ = d.keys
        with pytest.raises(AttributeError, match="collides with a built-in dict method"):
            _ = d.items
        # But [] access still works
        assert d["keys"] == "secret"
        assert d["items"] == [1, 2]

    def test_dict_method_name_no_collision(self) -> None:
        """When no data key collides, dict methods work normally."""
        d = DotDict({"name": "Alice"})
        assert callable(d.keys)
        assert callable(d.items)

    def test_non_string_keys_accessible_via_getitem(self) -> None:
        """Non-string keys work via [] but not dot (dot requires valid identifiers)."""
        d = DotDict()
        d[1] = "one"  # type: ignore
        assert d[1] == "one"
        # getattr() with a non-string arg raises TypeError before __getattr__
        # is even called, so there's no way to test "d.1" - it's a syntax error.

    def test_setattr_plain_value_after_nested(self) -> None:
        d = DotDict()
        d.a = {"b": 1}
        d.a.b = 2  # overwrite nested # type: ignore
        assert d.a.b == 2  # type: ignore

    def test_setattr_list_wraps_dicts(self) -> None:
        d = DotDict()
        d.entries = [{"x": 1}, {"y": 2}]
        assert isinstance(d.entries[0], DotDict)
        assert d.entries[0].x == 1

    def test_setattr_preserves_existing_dotdict(self) -> None:
        """__setattr__ should not re-wrap an already-existing DotDict."""
        inner = DotDict(x=1)
        d = DotDict()
        d.wrapped = inner
        assert d.wrapped is inner  # same object, not a copy

    def test_setattr_list_preserves_existing_dotdict(self) -> None:
        """__setattr__ should not re-wrap DotDict items inside a list."""
        inner = DotDict(x=1)
        d = DotDict()
        d.items_list = [inner, {"y": 2}]
        assert d.items_list[0] is inner
        assert isinstance(d.items_list[1], DotDict)


# ---------------------------------------------------------------------------
# decode() with dec_hook
# ---------------------------------------------------------------------------


class TestDecodeWithHook:
    def test_dec_hook_accepted(self) -> None:
        """The dec_hook parameter is forwarded to msgspec.json.decode.

        When decoding to plain ``dict`` the hook will not be invoked
        (msgspec handles all standard JSON types natively), but the
        parameter is accepted so that callers can pass a hook for use
        with custom :class:`msgspec.json.Decoder` instances later.
        """

        calls: list[tuple[type, object]] = []

        def my_hook(typ: type, obj: object) -> object:
            calls.append((typ, obj))
            raise TypeError(f"Cannot decode {typ}")

        d = DotDict.decode(b'{"event": "party"}', dec_hook=my_hook)
        assert d.event == "party"
        assert len(calls) == 0  # hook never called for dict decode
