"""Native typed FHIRPath for fhir.resources and Pydantic v2."""

from fhirpath_pydantic.expressions import Expression, literal, path, var
from fhirpath_pydantic.options import CustomFunction, EvaluationOptions, FunctionCall, TraceEvent
from fhirpath_pydantic.quantities import QuantityValue
from fhirpath_pydantic.query import CompiledQuery, compile, compile_as_array, compile_as_first, evaluate
from fhirpath_pydantic.types import FHIRPathError, UnsupportedFeatureError
from fhirpath_pydantic.validators import FHIRPathConstraint

__version__ = "0.1.0"
__all__ = [
    "CompiledQuery",
    "CustomFunction",
    "EvaluationOptions",
    "FunctionCall",
    "TraceEvent",
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
