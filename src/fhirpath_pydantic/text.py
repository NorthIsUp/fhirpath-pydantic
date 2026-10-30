"""Text operations owned by a validated, immutable Pydantic string value."""

import base64
import re

from pydantic import ConfigDict, RootModel

from fhirpath_pydantic.native import Item
from fhirpath_pydantic.operators import integer, string
from fhirpath_pydantic.types import FHIRPathError, UnsupportedFeatureError, Value


class StringValue(RootModel[str]):
    """Unicode text with FHIRPath singleton transformations and encoding."""

    model_config = ConfigDict(frozen=True)

    def encoded(self, format_name: str) -> str | None:
        """Encode UTF-8 text using the named upstream-compatible format."""
        data = self.root.encode("utf-8")
        match format_name:
            case "base64":
                return base64.b64encode(data).decode("ascii")
            case "urlbase64" | "base64url":
                return base64.urlsafe_b64encode(data).decode("ascii")
            case "hex":
                return data.hex()
            case _:
                return None

    def decoded(self, format_name: str) -> str | None:
        """Decode a checked encoding, rejecting malformed bytes and invalid UTF-8."""
        try:
            match format_name:
                case "base64":
                    data = base64.b64decode(self.root, validate=True)
                case "urlbase64" | "base64url":
                    padded = self.root + "=" * (-len(self.root) % 4)
                    data = base64.b64decode(padded, altchars=b"-_", validate=True)
                case "hex":
                    data = bytes.fromhex(self.root)
                case _:
                    return None
            return data.decode("utf-8")
        except ValueError as error:
            raise FHIRPathError("Invalid encoded text or UTF-8 sequence") from error

    def transform(self, name: str, params: list[list[Item]]) -> Value:
        """Apply a text operation after its collection contract has been checked."""
        value = self.root
        match name:
            case "length":
                return len(value)
            case "upper":
                return value.upper()
            case "lower":
                return value.lower()
            case "trim":
                return value.strip()
            case "toChars":
                characters: list[Value] = list(value)
                return characters
            case "substring":
                start = integer(params[0])
                if start < 0 or start >= len(value):
                    return None
                length = integer(params[1]) if len(params) > 1 else len(value)
                return value[start : start + max(length, 0)]
            case "startsWith":
                return value.startswith(string(params[0]))
            case "endsWith":
                return value.endswith(string(params[0]))
            case "contains":
                return string(params[0]) in value
            case "indexOf":
                return value.find(string(params[0]))
            case "matches":
                return re.search(string(params[0]), value, flags=re.DOTALL) is not None
            case "replace":
                return value.replace(string(params[0]), string(params[1]))
            case "replaceMatches":
                replacement = re.sub(r"\$(\d+)", r"\\g<\1>", string(params[1]))
                return re.sub(string(params[0]), replacement, value)
            case "split":
                separator = string(params[0])
                parts: list[Value] = list(value.split(separator) if separator else value)
                return parts
            case "encode":
                return self.encoded(string(params[0]))
            case "decode":
                return self.decoded(string(params[0]))
            case _:
                raise UnsupportedFeatureError(f"Unsupported string function: {name}")
