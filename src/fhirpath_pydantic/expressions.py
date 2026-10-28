"""Compose native syntax nodes without interpolating or reparsing query strings."""

from pydantic import BaseModel, ConfigDict

from fhirpath_pydantic.syntax import Node
from fhirpath_pydantic.types import Value


class Expression(BaseModel):
    """An immutable fluent query with explicit comparisons."""

    model_config = ConfigDict(frozen=True)
    node: Node

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

    def of_type(self, model: type[BaseModel]) -> Expression:
        """Filter to a native FHIR resource or datatype."""
        return self.call("ofType", Expression(node=Node(kind="TypeSpecifier", text=model.__name__)))

    def _binary(self, operator: str, other: Expression) -> Expression:
        return Expression(node=Node(kind="Binary", tokens=(operator,), children=(self.node, other.node)))

    def eq(self, other: Expression) -> Expression:
        """Compare values using FHIRPath equality."""
        return self._binary("=", other)

    def ne(self, other: Expression) -> Expression:
        """Compare values using FHIRPath inequality."""
        return self._binary("!=", other)

    def gt(self, other: Expression) -> Expression:
        """Test strict ordering."""
        return self._binary(">", other)

    def and_(self, other: Expression) -> Expression:
        """Compose predicates using three-valued Boolean conjunction."""
        return self._binary("and", other)

    def or_(self, other: Expression) -> Expression:
        """Compose predicates using three-valued Boolean disjunction."""
        return self._binary("or", other)


def path(*segments: str) -> Expression:
    """Build a field path; names are data, never parsed FHIRPath source."""
    expression = Expression(node=Node(kind="ThisInvocation"))
    for segment in segments:
        expression = expression.field(segment)
    return expression


def literal(value: Value) -> Expression:
    """Embed a native constant without quoting or string escaping."""
    return Expression(node=Node(kind="Constant", source="literal", value=value))


def var(name: str) -> Expression:
    """Bind a variable whose value is supplied at evaluation time."""
    return Expression(node=Node(kind="Variable", text=name))
