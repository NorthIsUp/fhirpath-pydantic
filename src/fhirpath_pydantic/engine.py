"""Per-evaluation state and native FHIRPath syntax evaluation."""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from fhirpath_pydantic.aggregates import AggregateCollection
from fhirpath_pydantic.native import Item, children, items, member, values
from fhirpath_pydantic.operators import binary, boolean, equal, integer, number, one, string, unique
from fhirpath_pydantic.options import EvaluationOptions, TraceEvent
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.references import ResolutionScope
from fhirpath_pydantic.scalars import convert, numeric, strings
from fhirpath_pydantic.syntax import Node
from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.types import FHIRPathError, UnsupportedFeatureError, Value


class State(BaseModel):
    """Call-local focus and variables, never shared between compiled evaluations."""

    model_config = ConfigDict(frozen=True)
    variables: dict[str, Value] = Field(default_factory=dict)
    options: EvaluationOptions = Field(default_factory=EvaluationOptions)
    resolution: ResolutionScope = Field(default_factory=ResolutionScope)
    context_focus: tuple[Item, ...] = ()
    index: int = 0
    total: tuple[Item, ...] = ()
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def resolve(self, focus: list[Item]) -> list[Item]:
        """Resolve local native references before consulting an explicit caller callback."""
        result: list[Item] = []
        for item in focus:
            references = [item.value] if isinstance(item.value, str) else item.member("reference").values()
            for reference in references:
                if not isinstance(reference, str):
                    continue
                resource = self.resolution.index.resolve(reference, item.owner)
                if resource is None:
                    resource = self.options.resolve(reference)
                if resource is not None:
                    result.extend(items(resource))
        return result

    def iterate(self, name: str, args: tuple[Node, ...], focus: list[Item]) -> list[Item]:
        """Evaluate collection macros in isolated child scopes."""
        if name == "exists" and not args:
            return items(bool(focus))
        if name == "aggregate":
            assert args
            accumulator = args[0]
            total = evaluate_node(args[1], focus, self) if len(args) > 1 else []
            for index, item in enumerate(focus):
                total = evaluate_node(
                    accumulator,
                    [item],
                    self.model_copy(update={"index": index, "total": tuple(total), "context_focus": (item,)}),
                )
            return total
        selected: list[Item] = []
        frontier = focus
        seen: list[Item] = []
        for _ in range(1000):
            projected: list[Item] = []
            for index, item in enumerate(frontier):
                result = evaluate_node(
                    args[0], [item], self.model_copy(update={"index": index, "context_focus": (item,)})
                )
                match name:
                    case "where":
                        if boolean(result) is True:
                            selected.append(item)
                    case "select":
                        selected.extend(result)
                    case "exists":
                        if boolean(result) is True:
                            return items(True)
                    case "all":
                        if boolean(result) is not True:
                            return items(False)
                    case "repeat":
                        projected.extend(result)
                    case _:
                        raise UnsupportedFeatureError(f"Unsupported iteration function: {name}")
            if name != "repeat":
                break
            frontier = [
                item
                for item in unique(projected)
                if not any(equal(item.system_value(), previous.system_value()) for previous in seen)
            ]
            if not frontier:
                break
            seen.extend(frontier)
            selected.extend(frontier)
            if len(selected) > 100_000:
                raise FHIRPathError("repeat() traversal limit exceeded")
        else:
            raise FHIRPathError("repeat() traversal limit exceeded")
        return items(name == "all") if name in {"all", "exists"} else selected

    def invoke(self, name: str, args: tuple[Node, ...], focus: list[Item]) -> list[Item]:
        """Check function arity before executing it in this evaluation scope."""
        if (custom := self.options.invocation_table.get(name)) is not None:
            custom.check_arity(len(args))
            arguments = tuple(values(self.evaluate(arg, list(self.context_focus))) for arg in args)
            return items(custom.invoke(values(focus), arguments))
        if (arity := _ARITY.get(name)) is None:
            raise UnsupportedFeatureError(f"Unsupported FHIRPath function: {name}")
        if not arity[0] <= len(args) <= arity[1]:
            raise FHIRPathError(f"Invalid argument count for {name}()")
        if name in {"where", "select", "exists", "all", "repeat", "aggregate"}:
            return self.iterate(name, args, focus)
        if name == "iif":
            state = self.model_copy(update={"context_focus": tuple(focus)})
            condition = evaluate_node(args[0], focus, state)
            branch = args[1] if boolean(condition) is True else args[2] if len(args) == 3 else None
            return evaluate_node(branch, focus, state) if branch else []
        if name == "coalesce":
            state = self.model_copy(update={"context_focus": tuple(focus)})
            for arg in args:
                if result := evaluate_node(arg, focus, state):
                    return result
            return []
        if name in {"ofType", "is", "as"}:
            target = args[0].name_value()
            if name == "ofType":
                return [item for item in focus if item.is_type(target, implicit=True)]
            if not focus:
                return []
            one(focus)
            matches = focus[0].is_type(target, implicit=name == "as")
            return items(matches) if name == "is" else focus if matches else []
        if name == "trace":
            label = string(self.evaluate(args[0], list(self.context_focus))) if args else ""
            if self.options.trace is not None:
                projected = (
                    self.model_copy(update={"context_focus": tuple(focus)}).evaluate(args[1], focus)
                    if len(args) > 1
                    else focus
                )
                self.options.trace(TraceEvent(label=label, values=values(projected)))
            return focus
        params = [evaluate_node(arg, list(self.context_focus), self) for arg in args]
        match name:
            case "resolve":
                return self.resolve(focus)
            case "sum" | "avg" | "min" | "max":
                return AggregateCollection.model_construct(root=focus).aggregate(name).root
            case "toQuantity" | "convertsToQuantity":
                if not focus or params and not params[0]:
                    return []
                quantity = QuantityValue.from_value(one(focus))
                if quantity is not None and params:
                    quantity = quantity.convert_to(string(params[0]))
                return items(quantity is not None) if name == "convertsToQuantity" else items(quantity)
            case "empty":
                return items(not focus)
            case "count":
                return items(len(focus))
            case "first":
                return focus[:1]
            case "last":
                return focus[-1:]
            case "tail":
                return focus[1:]
            case "single":
                one(focus)
                return focus
            case "skip" | "take":
                if not params[0]:
                    return []
                count = max(0, integer(params[0]))
                return focus[count:] if name == "skip" else focus[:count]
            case "not":
                value = boolean(focus)
                return items(not value) if value is not None else []
            case "distinct":
                return unique(focus)
            case "isDistinct":
                return items(len(unique(focus)) == len(focus))
            case "allTrue" | "anyTrue" | "allFalse" | "anyFalse":
                if any(not isinstance(item.value, bool) for item in focus):
                    raise FHIRPathError("Boolean aggregation requires Boolean values")
                matches = [item.value is (name in {"allTrue", "anyTrue"}) for item in focus]
                return items(all(matches) if name.startswith("all") else any(matches))
            case "union":
                return unique([*focus, *params[0]])
            case "combine":
                return [*focus, *params[0]]
            case "intersect" | "exclude":
                result = [
                    item
                    for item in focus
                    if any(equal(item.system_value(), other.system_value()) for other in params[0])
                    is (name == "intersect")
                ]
                return unique(result) if name == "intersect" else result
            case "subsetOf" | "supersetOf":
                subset, superset = (focus, params[0]) if name == "subsetOf" else (params[0], focus)
                return items(
                    all(any(equal(item.system_value(), other.system_value()) for other in superset) for item in subset)
                )
            case "children":
                return children(focus)
            case "descendants":
                result: list[Item] = []
                frontier = children(focus)
                while frontier:
                    result.extend(frontier)
                    if len(result) > 100_000:
                        raise FHIRPathError("Traversal limit exceeded")
                    frontier = children(frontier)
                return result
            case "extension":
                url = string(params[0])
                return [item for item in member(focus, "extension") if values(member([item], "url")) == [url]]
            case "hasValue":
                return items(
                    len(focus) == 1
                    and focus[0].value is not None
                    and not isinstance(focus[0].value, (BaseModel, list, dict))
                )
            case "getValue":
                value = one(focus)
                return (
                    items(value)
                    if value is not None
                    and (isinstance(value, TemporalValue) or not isinstance(value, (BaseModel, list, dict)))
                    else []
                )
            case "type":
                return items([item.type_info() for item in focus])
            case "now":
                return items(self.timestamp)
            case "today":
                return items(self.timestamp.date())
            case "timeOfDay":
                return items(self.timestamp.time())
            case "join":
                separator = string(params[0]) if params else ""
                if any(not isinstance(item.value, str) for item in focus):
                    raise FHIRPathError("join() requires String values")
                return items(separator.join(item.value for item in focus if isinstance(item.value, str)))
            case _:
                if name in {"toChars"}:
                    return strings(name, focus, params)
                if name.startswith("to") or name.startswith("convertsTo"):
                    return convert(name, focus)
                if name in {"abs", "ceiling", "floor", "truncate", "sqrt", "exp", "ln", "power", "log", "round"}:
                    return numeric(name, focus, params)
                return strings(name, focus, params)

    def evaluate(self, node: Node, focus: list[Item]) -> list[Item]:
        """Execute a parsed or programmatically built syntax node."""
        if node.source == "literal":
            return items(node.value)
        match node.kind:
            case "TermExpression" | "InvocationTerm" | "LiteralTerm" | "ParenthesizedTerm":
                return evaluate_node(node.children[0], focus, self)
            case "InvocationExpression":
                for child in node.children:
                    focus = evaluate_node(child, focus, self)
                return focus
            case "MemberInvocation":
                return member(focus, node.children[0].name_value())
            case "ThisInvocation":
                return list(self.context_focus)
            case "IndexInvocation":
                return items(self.index)
            case "TotalInvocation":
                return list(self.total)
            case "ExternalConstantTerm" | "Variable":
                name = node.children[0].name_value() if node.kind == "ExternalConstantTerm" else node.text
                if name not in self.variables:
                    raise FHIRPathError(f"Undefined environment variable: {name}")
                return items(self.variables[name])
            case "BooleanLiteral":
                return items(node.text == "true")
            case "NumberLiteral":
                return items(Decimal(node.text) if "." in node.text else int(node.text))
            case "StringLiteral":
                return items(node.string_value())
            case "NullLiteral":
                return []
            case "DateTimeLiteral":
                return items(TemporalValue.from_text(node.text, "DateTime" if "T" in node.text else "Date").native())
            case "TimeLiteral":
                return items(TemporalValue.from_text(node.text, "Time").native())
            case "QuantityLiteral":
                quantity = QuantityValue.from_text(node.text)
                if quantity is None:
                    raise FHIRPathError("Invalid Quantity literal")
                return items(quantity)
            case "PolarityExpression":
                result = evaluate_node(node.children[0], focus, self)
                if not result:
                    return []
                native = one(result)
                if QuantityValue.is_quantity(native):
                    quantity = QuantityValue.operand(native)
                    return items(quantity.negated() if quantity is not None and node.tokens[0] == "-" else quantity)
                value = native if isinstance(native, int) and not isinstance(native, bool) else number(native)
                return items(-value if node.tokens[0] == "-" else value)
            case "IndexerExpression":
                collection = evaluate_node(node.children[0], focus, self)
                index = evaluate_node(node.children[1], focus, self)
                if not index:
                    return []
                position = integer(index)
                return [collection[position]] if 0 <= position < len(collection) else []
            case "FunctionInvocation":
                function = node.children[0]
                assert function.children
                name = function.children[0].name_value()
                args = function.children[1].children if len(function.children) > 1 else ()
                return self.invoke(name, args, focus)
            case "Call":
                return self.invoke(node.text, node.children[1:], evaluate_node(node.children[0], focus, self))
            case "TypeExpression":
                collection = evaluate_node(node.children[0], focus, self)
                if not collection:
                    return []
                one(collection)
                matches = collection[0].is_type(node.children[1].name_value(), implicit=node.tokens[0] == "as")
                return items(matches) if node.tokens[0] == "is" else collection if matches else []
            case (
                "UnionExpression"
                | "EqualityExpression"
                | "InequalityExpression"
                | "AdditiveExpression"
                | "MultiplicativeExpression"
                | "MembershipExpression"
                | "AndExpression"
                | "OrExpression"
                | "XorExpression"
                | "ImpliesExpression"
                | "Binary"
            ):
                left = evaluate_node(node.children[0], focus, self)
                operator = node.tokens[0]
                if operator == "and" and boolean(left) is False:
                    return items(False)
                if operator == "or" and boolean(left) is True:
                    return items(True)
                if operator == "implies" and boolean(left) is False:
                    return items(True)
                return binary(operator, left, evaluate_node(node.children[1], focus, self))
            case _:
                raise UnsupportedFeatureError(f"Unsupported grammar node: {node.kind}")


def evaluate_node(node: Node, focus: list[Item], state: State) -> list[Item]:
    """Evaluate through the call-local state model."""
    return state.evaluate(node, focus)


_ARITY: dict[str, tuple[int, int]] = {
    "type": (0, 0),
    "resolve": (0, 0),
    "trace": (0, 2),
    "sum": (0, 0),
    "avg": (0, 0),
    "min": (0, 0),
    "max": (0, 0),
    "trim": (0, 0),
    "encode": (1, 1),
    "decode": (1, 1),
    "toQuantity": (0, 1),
    "convertsToQuantity": (0, 1),
    **dict.fromkeys(
        (
            "empty",
            "count",
            "first",
            "last",
            "tail",
            "single",
            "not",
            "distinct",
            "isDistinct",
            "allTrue",
            "anyTrue",
            "allFalse",
            "anyFalse",
            "children",
            "descendants",
            "hasValue",
            "getValue",
            "length",
            "upper",
            "lower",
            "toChars",
            "toString",
            "toBoolean",
            "toInteger",
            "toDecimal",
            "toDate",
            "toDateTime",
            "toTime",
            "convertsToString",
            "convertsToBoolean",
            "convertsToInteger",
            "convertsToDecimal",
            "convertsToDate",
            "convertsToDateTime",
            "convertsToTime",
            "abs",
            "ceiling",
            "floor",
            "truncate",
            "sqrt",
            "exp",
            "ln",
            "now",
            "today",
            "timeOfDay",
        ),
        (0, 0),
    ),
    **dict.fromkeys(
        (
            "where",
            "select",
            "all",
            "repeat",
            "skip",
            "take",
            "ofType",
            "is",
            "as",
            "union",
            "intersect",
            "exclude",
            "subsetOf",
            "supersetOf",
            "startsWith",
            "endsWith",
            "contains",
            "indexOf",
            "matches",
            "split",
            "power",
            "log",
            "extension",
        ),
        (1, 1),
    ),
    "exists": (0, 1),
    "iif": (2, 3),
    "combine": (1, 2),
    "substring": (1, 2),
    "replace": (2, 2),
    "replaceMatches": (2, 2),
    "round": (0, 1),
    "join": (0, 1),
    "aggregate": (1, 2),
    "coalesce": (1, 100),
}
