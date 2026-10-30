"""Native typed FHIRPath for fhir.resources and Pydantic v2."""

from fhirpath_pydantic.expressions import BinaryOperator, Expression, literal, path, var
from fhirpath_pydantic.options import (
    CustomFunction,
    CustomMacro,
    EvaluationOptions,
    FunctionArgument,
    FunctionArity,
    FunctionCall,
    MacroCall,
    TraceEvent,
)
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.query import CompiledQuery, compile, compile_as_array, compile_as_first, evaluate
from fhirpath_pydantic.temporal import TemporalValue
from fhirpath_pydantic.type_info import TypeInfo
from fhirpath_pydantic.types import FHIRPathError, InputValue, UnsupportedFeatureError
from fhirpath_pydantic.validators import FHIRPathConstraint

__version__ = "0.1.0"
__all__ = [
    "BinaryOperator",
    "InputValue",
    "CompiledQuery",
    "CustomFunction",
    "CustomMacro",
    "FunctionArgument",
    "FunctionArity",
    "MacroCall",
    "EvaluationOptions",
    "FunctionCall",
    "TraceEvent",
    "TemporalValue",
    "TypeInfo",
    "Expression",
    "FHIRPathConstraint",
    "FHIRPathError",
    "QuantityValue",
    "UnsupportedFeatureError",
    "compile",
    "compile_as_array",
    "compile_as_first",
    "evaluate",
    "literal",
    "path",
    "var",
]
