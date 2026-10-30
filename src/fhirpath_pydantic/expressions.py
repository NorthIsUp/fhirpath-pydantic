"""Compose native syntax nodes without interpolating or reparsing query strings."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from fhirpath_pydantic.native import NativeInput
from fhirpath_pydantic.syntax import Node
from fhirpath_pydantic.types import InputValue

type BinaryOperator = Literal[
    "|",
    "=",
    "!=",
    "~",
    "!~",
    "<",
    "<=",
    ">",
    ">=",
    "in",
    "contains",
    "&",
    "+",
    "-",
    "*",
    "/",
    "mod",
    "div",
    "or",
    "and",
    "xor",
    "implies",
]
_BINARY_OPERATOR = TypeAdapter[BinaryOperator](BinaryOperator)


class Expression(BaseModel):
    """An immutable fluent query with explicit comparisons."""

    model_config = ConfigDict(frozen=True)
    node: Node

    @classmethod
    def from_path(cls, *segments: str) -> Expression:
        """Construct a field path whose segments remain native syntax data."""
        expression = cls(node=Node(kind="ThisInvocation"))
        for segment in segments:
            expression = expression.field(segment)
        return expression

    @classmethod
    def from_literal(cls, value: InputValue) -> Expression:
        """Construct a native constant without quoting or string interpolation."""
        return cls(node=Node(kind="Constant", source="literal", value=NativeInput.from_value(value).root))

    @classmethod
    def from_variable(cls, name: str) -> Expression:
        """Construct a runtime variable reference without parsing its name."""
        return cls(node=Node(kind="Variable", text=name))

    @classmethod
    def from_type(cls, target: str | type[BaseModel]) -> Expression:
        """Keep a type name or actual Pydantic class as a native syntax argument."""
        return cls(
            node=Node(
                kind="TypeSpecifier",
                text=target if isinstance(target, str) else target.__name__,
                target_model=None if isinstance(target, str) else target,
            )
        )

    def field(self, name: str) -> Expression:
        """Select a FHIR alias or choice field."""
        selection = Node(kind="MemberInvocation", children=(Node(kind="Identifier", text=name),))
        return Expression(node=Node(kind="InvocationExpression", children=(self.node, selection)))

    def call(self, name: str, *args: Expression) -> Expression:
        """Invoke a function using already constructed syntax nodes."""
        return Expression(node=Node(kind="Call", text=name, children=(self.node, *(arg.node for arg in args))))

    def where(self, predicate: Expression) -> Expression:
        """Filter by a predicate evaluated on each collection element."""
        return self.call("where", predicate)

    def select(self, projection: Expression) -> Expression:
        """Project each element and flatten the results."""
        return self.call("select", projection)

    def first(self) -> Expression:
        """Select the first element, retaining empty collections."""
        return self.call("first")

    def exists(self) -> Expression:
        """Test whether this collection has an element."""
        return self.call("exists")

    def is_type(self, target: str | type[BaseModel]) -> Expression:
        """Test a singleton's declared type or actual native model class."""
        return self.call("is", Expression.from_type(target))

    def as_type(self, target: str | type[BaseModel]) -> Expression:
        """Keep a matching singleton without converting or serializing its value."""
        return self.call("as", Expression.from_type(target))

    def of_type(self, model: str | type[BaseModel]) -> Expression:
        """Filter by declared FHIR/System type name or actual Pydantic class."""
        return self.call("ofType", Expression.from_type(model))

    def binary(self, operator: BinaryOperator, other: Expression) -> Expression:
        """Compose a checked native operator without rendering either operand as text."""
        token = _BINARY_OPERATOR.validate_python(operator, strict=True)
        return Expression(node=Node(kind="Binary", tokens=(token,), children=(self.node, other.node)))

    def eq(self, other: Expression) -> Expression:
        """Compare values using FHIRPath equality."""
        return self.binary("=", other)

    def ne(self, other: Expression) -> Expression:
        """Compare values using FHIRPath inequality."""
        return self.binary("!=", other)

    def gt(self, other: Expression) -> Expression:
        """Test strict ordering."""
        return self.binary(">", other)

    def and_(self, other: Expression) -> Expression:
        """Compose predicates using three-valued Boolean conjunction."""
        return self.binary("and", other)

    def or_(self, other: Expression) -> Expression:
        """Compose predicates using three-valued Boolean disjunction."""
        return self.binary("or", other)


def path(*segments: str) -> Expression:
    """Build a field path without parsing its names as query source."""
    return Expression.from_path(*segments)


def literal(value: InputValue) -> Expression:
    """Embed a native constant without quoting or string escaping."""
    return Expression.from_literal(value)


def var(name: str) -> Expression:
    """Bind a variable whose value is supplied at evaluation time."""
    return Expression.from_variable(name)
