"""Micro-benchmarks comparing structhook against raw msgspec.

Measures the overhead structhook adds per operation (encode, decode, dump, convert)
across its feature set: fast path, serialize/deserialize/validate hooks,
computed fields, and excluded fields.

Usage::

    python benchmarks/bench.py
"""

import timeit
from typing import Any

import msgspec

from structhook import DotDict, HookStruct, computed_field, deserialize, field, serialize, validate

# ---------------------------------------------------------------------------
# Number of iterations per benchmark.  Calibrated so the fastest operation
# (msgspec encode) takes roughly 0.1-0.2 s per trial.
# ---------------------------------------------------------------------------
NUMBER = 200_000
REPEAT = 5

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

PAYLOAD = b'{"name":"alice","age":30,"score":95.5,"active":true,"tags":["dev","admin"]}'
PAYLOAD_ALL = (
    b'{"name":" alice ","age":30,"score":95.5,"active":true,'
    b'"tags":["dev","admin"],"secret":"hidden"}'
)
DATA = {"name": "alice", "age": 30, "score": 95.5, "active": True, "tags": ["dev", "admin"]}
DATA_ALL = {**DATA, "secret": "hidden"}

NESTED_JSON = b'{"user":{"name":"alice","profile":{"theme":"dark","visits":[{"page":"home","count":5},{"page":"about","count":2}]}}}'
NESTED_DICT = {
    "user": {
        "name": "alice",
        "profile": {
            "theme": "dark",
            "visits": [{"page": "home", "count": 5}, {"page": "about", "count": 2}],
        },
    }
}

# ---------------------------------------------------------------------------
# Model definitions (module-level so timeit can reference them)
# ---------------------------------------------------------------------------


class _MsgspecBaseline(msgspec.Struct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]


class _FastPath(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]


class _WithSerialize(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]

    @serialize("name")
    def _upper_name(self, v: str) -> str:
        return v.upper()


class _WithDeserialize(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]

    @deserialize("name")
    def _clean_name(cls, v: str) -> str:
        return v.strip().title()


class _WithValidate(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]

    @validate("age")
    def _check_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"invalid age: {v}")
        return v


class _WithComputed(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]

    @computed_field
    def summary(self) -> str:
        return f"{self.name} ({self.age})"


class _WithExcluded(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]
    secret: str = field(exclude=True, default="hidden")


class _WithAll(HookStruct):
    name: str
    age: int
    score: float
    active: bool
    tags: list[str]
    secret: str = field(exclude=True, default="hidden")

    @computed_field
    def summary(self) -> str:
        return f"{self.name} ({self.age})"

    @serialize("name")
    def _upper_name(self, v: str) -> str:
        return v.upper()

    @deserialize("name")
    def _clean_name(cls, v: str) -> str:
        return v.strip().title()

    @validate("age")
    def _check_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"invalid age: {v}")
        return v


# ---------------------------------------------------------------------------
# Test instances (created once, used by timeit stmts)
# ---------------------------------------------------------------------------

_baseline = _MsgspecBaseline(name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"])
_fast = _FastPath(name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"])
_serialize = _WithSerialize(name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"])
_deserialize = _WithDeserialize(
    name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"]
)
_validate = _WithValidate(name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"])
_computed = _WithComputed(name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"])
_excluded = _WithExcluded(
    name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"], secret="hidden"
)
_all = _WithAll(
    name="alice", age=30, score=95.5, active=True, tags=["dev", "admin"], secret="hidden"
)

# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------

Benchmark = tuple[str, str, str]  # (label, setup, stmt)

ENCODE_BENCHES: list[Benchmark] = [
    (
        "msgspec.Struct (baseline)",
        "import msgspec, __main__",
        "msgspec.json.encode(__main__._baseline)",
    ),
    (
        "HookStruct fast path",
        "import __main__",
        "__main__._fast.encode()",
    ),
    (
        "+ serialize hook",
        "import __main__",
        "__main__._serialize.encode()",
    ),
    (
        "+ computed field",
        "import __main__",
        "__main__._computed.encode()",
    ),
    (
        "+ excluded field",
        "import __main__",
        "__main__._excluded.encode()",
    ),
    (
        "+ all features",
        "import __main__",
        "__main__._all.encode()",
    ),
]

DECODE_BENCHES: list[Benchmark] = [
    (
        "msgspec.Struct (baseline)",
        "import msgspec, __main__",
        "msgspec.json.decode(__main__.PAYLOAD, type=__main__._MsgspecBaseline)",
    ),
    (
        "HookStruct fast path",
        "import __main__",
        "__main__._FastPath.decode(__main__.PAYLOAD)",
    ),
    (
        "+ deserialize hook",
        "import __main__",
        "__main__._WithDeserialize.decode(__main__.PAYLOAD)",
    ),
    (
        "+ validate hook",
        "import __main__",
        "__main__._WithValidate.decode(__main__.PAYLOAD)",
    ),
    (
        "+ both hooks",
        "import __main__",
        "__main__._WithAll.decode(__main__.PAYLOAD_ALL)",
    ),
]

DUMP_BENCHES: list[Benchmark] = [
    (
        "msgspec.Struct (baseline)",
        "import msgspec, __main__",
        "msgspec.to_builtins(__main__._baseline)",
    ),
    (
        "HookStruct fast path",
        "import __main__",
        "__main__._fast.dump()",
    ),
    (
        "+ serialize hook",
        "import __main__",
        "__main__._serialize.dump()",
    ),
    (
        "+ computed field",
        "import __main__",
        "__main__._computed.dump()",
    ),
    (
        "+ excluded field",
        "import __main__",
        "__main__._excluded.dump()",
    ),
    (
        "+ all features",
        "import __main__",
        "__main__._all.dump()",
    ),
]

CONVERT_BENCHES: list[Benchmark] = [
    (
        "msgspec.Struct (baseline)",
        "import msgspec, __main__",
        "msgspec.convert(__main__.DATA, __main__._MsgspecBaseline)",
    ),
    (
        "HookStruct fast path",
        "import __main__",
        "__main__._FastPath.convert(__main__.DATA)",
    ),
    (
        "+ deserialize hook",
        "import __main__",
        "__main__._WithDeserialize.convert(__main__.DATA)",
    ),
    (
        "+ validate hook",
        "import __main__",
        "__main__._WithValidate.convert(__main__.DATA)",
    ),
    (
        "+ both hooks",
        "import __main__",
        "__main__._WithAll.convert(__main__.DATA_ALL)",
    ),
]

DOTDICT_BENCHES: list[Benchmark] = [
    (
        "dict (baseline)",
        "import msgspec",
        "msgspec.json.decode(__import__('__main__').NESTED_JSON, type=dict)",
    ),
    (
        "DotDict.decode",
        "from structhook import DotDict",
        "DotDict.decode(__import__('__main__').NESTED_JSON)",
    ),
]


def _dotdict_instance() -> DotDict:
    return DotDict.decode(NESTED_JSON)


_dd = _dotdict_instance()


def run_benchmarks(
    benches: list[Benchmark],
    title: str,
    number: int = NUMBER,
    repeat: int = REPEAT,
) -> list[tuple[str, float, float]]:
    """Run a set of benchmarks and return (label, ops_per_sec, vs_baseline) tuples."""
    results: list[tuple[str, float, float]] = []
    baseline_ops: float | None = None

    for label, setup, stmt in benches:
        timer = timeit.Timer(stmt, setup)
        raw_times = timer.repeat(repeat, number)
        best = min(raw_times)
        ops_per_sec = number / best

        if baseline_ops is None:
            baseline_ops = ops_per_sec
            ratio = 1.0
        else:
            ratio = ops_per_sec / baseline_ops

        results.append((label, ops_per_sec, ratio))

    # --- print ---------------------------------------------------------------
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"  ({number:,} iterations, best of {repeat} repeats)")
    print(f"{'=' * 60}")
    print(f"{'':<34} {'ops/sec':>12} {'vs msgspec':>10}")
    print(f"{'-' * 34} {'-' * 12} {'-' * 10}")

    for label, ops, ratio in results:
        print(f"{label:<34} {ops:>12,.0f} {ratio:>9.2f}x")

    return results


def run_dotdict_access() -> None:
    """Benchmark dot-access vs bracket-access on a nested DotDict."""
    d = _dotdict_instance()
    number = 1_000_000
    repeat = REPEAT

    print(f"\n{'=' * 60}")
    print(f"  DotDict attribute vs bracket access")
    print(f"  ({number:,} iterations, best of {repeat} repeats)")
    print(f"{'=' * 60}")
    print(f"{'':<34} {'ops/sec':>12} {'vs bracket':>10}")
    print(f"{'-' * 34} {'-' * 12} {'-' * 10}")

    # bracket access (baseline)
    bracket_timer = timeit.Timer(
        "_d['user']['profile']['theme']",
        "from __main__ import _dotdict_instance; _d = _dotdict_instance()",
    )
    bracket_best = min(bracket_timer.repeat(repeat, number))
    bracket_ops = number / bracket_best
    print(f"{'bracket access (baseline)':<34} {bracket_ops:>12,.0f} {1.0:>9.2f}x")

    # dot access
    dot_timer = timeit.Timer(
        "_d.user.profile.theme",
        "from __main__ import _dotdict_instance; _d = _dotdict_instance()",
    )
    dot_best = min(dot_timer.repeat(repeat, number))
    dot_ops = number / dot_best
    print(f"{'dot access':<34} {dot_ops:>12,.0f} {dot_ops / bracket_ops:>9.2f}x")

    # dict construction (baseline)
    const_number = 100_000
    print(f"\n  Construction from nested dict ({const_number:,} iterations)")
    print(f"{'':<34} {'ops/sec':>12} {'vs dict':>10}")
    print(f"{'-' * 34} {'-' * 12} {'-' * 10}")

    dict_timer = timeit.Timer(
        "dict(__import__('__main__').NESTED_DICT)",
        "import __main__",
    )
    dict_best = min(dict_timer.repeat(repeat, const_number))
    dict_ops = const_number / dict_best
    print(f"{'dict() (baseline)':<34} {dict_ops:>12,.0f} {1.0:>9.2f}x")

    dd_timer = timeit.Timer(
        "DotDict(__import__('__main__').NESTED_DICT)",
        "from structhook import DotDict; import __main__",
    )
    dd_best = min(dd_timer.repeat(repeat, const_number))
    dd_ops = const_number / dd_best
    print(f"{'DotDict()':<34} {dd_ops:>12,.0f} {dd_ops / dict_ops:>9.2f}x")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("structhook benchmarks — vs msgspec.Struct")
    print(f"Python {__import__('sys').version.split()[0]}")
    print(f"msgspec {msgspec.__version__}")

    run_benchmarks(ENCODE_BENCHES, "Encode (model -> bytes)")
    run_benchmarks(DECODE_BENCHES, "Decode (bytes -> model)")
    run_benchmarks(DUMP_BENCHES, "Dump (model -> dict)")
    run_benchmarks(CONVERT_BENCHES, "Convert (dict -> model)")
    run_benchmarks(DOTDICT_BENCHES, "DotDict decode (bytes -> dict/DotDict)")
    run_dotdict_access()

    print()


if __name__ == "__main__":
    main()
