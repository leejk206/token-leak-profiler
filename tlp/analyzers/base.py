from __future__ import annotations
from typing import ClassVar, Any
from tlp.types import ParsedTrace, LeakReport, LeverCategory, UsageBucket, MeasurementBasis


class _Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, type["BaseAnalyzer"]] = {}

    def register(self, cls: type["BaseAnalyzer"]) -> None:
        if cls.name in self._by_name:
            raise ValueError(f"duplicate analyzer name: {cls.name}")
        self._by_name[cls.name] = cls

    def unregister(self, name: str) -> None:
        self._by_name.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def all(self) -> list[type["BaseAnalyzer"]]:
        return [self._by_name[n] for n in self.names()]

    def get(self, name: str) -> type["BaseAnalyzer"]:
        return self._by_name[name]


registry = _Registry()


class BaseAnalyzer:
    name: ClassVar[str]
    lever: ClassVar[LeverCategory]
    usage_bucket: ClassVar[UsageBucket]
    prescription: ClassVar[str | None]
    measurement_basis: ClassVar[MeasurementBasis]

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        for attr in ("name", "lever", "usage_bucket", "prescription", "measurement_basis"):
            if not hasattr(cls, attr):
                raise TypeError(f"{cls.__name__} missing required class attribute: {attr}")
        if cls.measurement_basis not in ("measured", "estimated", "heuristic"):
            raise TypeError(
                f"{cls.__name__}.measurement_basis must be 'measured', 'estimated', or 'heuristic'; "
                f"got {cls.measurement_basis!r}"
            )
        registry.register(cls)

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        raise NotImplementedError
