"""Validate the inherited JSON fixture catalogue before exposing its values."""

from pathlib import Path

from pydantic import TypeAdapter

from fhirpath_pydantic.types import Value

resources: dict[str, Value] = {
    path.name: TypeAdapter(Value).validate_json(path.read_bytes()) for path in Path(__file__).parent.glob("*.json")
}
