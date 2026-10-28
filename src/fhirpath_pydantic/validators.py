"""FHIRPath invariants integrated with Pydantic validation."""

from functools import cached_property

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator

from fhirpath_pydantic.query import CompiledQuery, compile
from fhirpath_pydantic.syntax import parse


class FHIRPathConstraint(BaseModel):
    """A FHIR invariant requiring exactly one true Boolean result."""

    model_config = ConfigDict(frozen=True)
    expression: str
    message: str = "FHIRPath invariant failed"

    @field_validator("expression")
    @classmethod
    def valid_expression(cls, expression: str) -> str:
        """Reject invalid invariant syntax when defining the constraint."""
        parse(expression)
        return expression

    @cached_property
    def query(self) -> CompiledQuery[bool]:
        """Create the result adapter once, retaining only syntax and schema."""
        return compile(self.expression, output_type=bool)

    def check[T: BaseModel](self, resource: T) -> T:
        """Preserve the validated resource when the invariant succeeds."""
        if self.query(resource) != [True]:
            raise ValueError(self.message)
        return resource

    def after_validator(self) -> AfterValidator:
        """Compose with Annotated or an existing Pydantic field validator."""
        return AfterValidator(self.check)
