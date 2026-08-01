from pydantic import BaseModel, field_validator
from typing import Any, Literal


class MappingContext(BaseModel):
    parcel_attrs: dict[str, Any] = {}
    poi_hits: list[dict[str, Any]] = []
    zone_membership: list[str] = []
    imagery_signals: dict[str, Any] = {}

    def get(self, field: str, default: Any = None) -> Any:
        if field in self.parcel_attrs:
            return self.parcel_attrs[field]
        if field == "in_ecological_redline":
            return "in_ecological_redline" in self.zone_membership
        if field == "in_basic_farmland":
            return "in_basic_farmland" in self.zone_membership
        if field == "near_hazard":
            return self.imagery_signals.get("near_hazard", False)
        if field == "base_zone":
            return self.parcel_attrs.get("base_zone", "")
        return default


class Condition(BaseModel):
    kind: Literal["func", "comparison", "and", "or", "not", "null"]
    func: str | None = None
    args: list[Any] = []
    field: str | None = None
    op: Literal["==", "!=", "in", "starts_with", "gt", "lt"] | None = None
    value: Any = None
    children: list["Condition"] = []

    def evaluate(self, ctx: MappingContext) -> bool:
        match self.kind:
            case "null":
                return True
            case "and":
                return all(c.evaluate(ctx) for c in self.children)
            case "or":
                return any(c.evaluate(ctx) for c in self.children)
            case "not":
                return not (self.children and self.children[0].evaluate(ctx))
            case "comparison":
                actual = ctx.get(self.field)
                if self.op == "==":
                    return actual == self.value
                if self.op == "!=":
                    return actual != self.value
                if self.op == "in":
                    return actual in (self.value or [])
                if self.op == "starts_with":
                    return str(actual).startswith(str(self.value))
                if self.op == "gt":
                    return float(actual) > float(self.value)
                if self.op == "lt":
                    return float(actual) < float(self.value)
                return False
            case "func":
                fn = _BUILTIN_FUNCS.get(self.func or "")
                if fn is None:
                    return False
                return fn(ctx, *self.args)
            case _:
                return False


def _func_poi_match(ctx: MappingContext, *keywords: str) -> bool:
    if not keywords:
        return False
    for hit in ctx.poi_hits:
        name = str(hit.get("name", "")).lower()
        for kw in keywords:
            if kw.lower() in name:
                return True
    return False


def _func_field_equals(ctx: MappingContext, field: str, value: Any) -> bool:
    return ctx.get(field) == value


def _func_within_zone(ctx: MappingContext, zone_code: str) -> bool:
    return zone_code in ctx.zone_membership


def _func_imagery(ctx: MappingContext, name: str) -> bool:
    return bool(ctx.imagery_signals.get(name, False))


def _func_area_gt(ctx: MappingContext, hectares: float) -> bool:
    area = float(ctx.parcel_attrs.get("area_ha", 0) or 0)
    return area > hectares


_BUILTIN_FUNCS: dict[str, Any] = {
    "poi_match": _func_poi_match,
    "field_equals": _func_field_equals,
    "within_zone": _func_within_zone,
    "imagery_indicator": _func_imagery,
    "area_gt": _func_area_gt,
}


def condition_from_yaml(data: dict[str, Any]) -> Condition:
    if not data:
        return Condition(kind="null")
    return Condition(**data)


__all__ = [
    "MappingContext",
    "Condition",
    "condition_from_yaml",
    "_BUILTIN_FUNCS",
]