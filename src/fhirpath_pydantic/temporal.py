"""Precision-aware temporal values without inventing missing components."""

import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from typing import Literal, Self, override

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fhirpath_pydantic.decimal_value import DecimalValue
from fhirpath_pydantic.quantities import QuantityUnit, QuantityValue
from fhirpath_pydantic.types import FHIRPathError, Value


class TemporalValue(BaseModel):
    """A partial ISO temporal; complete values can use native Python types."""

    model_config = ConfigDict(frozen=True)
    kind: Literal["Date", "DateTime", "Time"]
    year: int | None = Field(default=None, ge=1, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    second: Decimal | None = Field(default=None, ge=0, lt=60)
    offset_minutes: int | None = Field(default=None, ge=-840, le=840)

    @model_validator(mode="after")
    def valid_precision(self) -> Self:
        """Require contiguous components and validate actual calendar dates."""
        fields = (self.year, self.month, self.day, self.hour, self.minute, self.second)
        if self.kind == "Time":
            if any(value is not None for value in fields[:3]):
                raise ValueError("Time cannot contain date components")
            fields = fields[3:]
        elif self.year is None:
            raise ValueError("A date requires a year")
        if self.kind == "Date" and any(value is not None for value in fields[3:]):
            raise ValueError("Date cannot contain time components")
        missing = False
        for value in fields:
            if missing and value is not None:
                raise ValueError("Temporal precision must be contiguous")
            missing = missing or value is None
        if self.kind == "Time" and self.hour is None:
            raise ValueError("A time requires an hour")
        if self.year is not None and self.month is not None and self.day is not None:
            date(self.year, self.month, self.day)
        if self.offset_minutes is not None and self.hour is None:
            raise ValueError("A timezone offset requires a time")
        return self

    @classmethod
    def from_text(cls, text: str, kind: Literal["Date", "DateTime", "Time"]) -> Self:
        """Parse partial ISO syntax while retaining its declared precision."""
        text = text.removeprefix("@")
        date_part, separator, time_part = text.partition("T")
        if kind == "Time":
            time_part = text.removeprefix("T")
            date_part = ""
        elif kind == "Date" and separator:
            raise FHIRPathError("A Date string cannot include a time")
        parts: dict[str, int | Decimal | str] = {"kind": kind}
        if kind != "Time":
            if (match := re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", date_part)) is None:
                raise FHIRPathError("Invalid temporal date")
            for name, value in zip(("year", "month", "day"), match.groups(), strict=True):
                if value is not None:
                    parts[name] = int(value)
        if time_part:
            match = re.fullmatch(r"(\d{2})(?::(\d{2})(?::(\d{2}(?:\.\d+)?))?)?(Z|[+-]\d{2}:\d{2})?", time_part)
            if match is None:
                raise FHIRPathError("Invalid temporal time")
            hour, minute, second, offset = match.groups()
            parts["hour"] = int(hour)
            if minute is not None:
                parts["minute"] = int(minute)
            if second is not None:
                parts["second"] = Decimal(second)
            if offset is not None:
                if offset == "Z":
                    parts["offset_minutes"] = 0
                else:
                    hours, minutes = int(offset[1:3]), int(offset[4:6])
                    if minutes > 59:
                        raise FHIRPathError("Invalid timezone minutes")
                    parts["offset_minutes"] = (1 if offset[0] == "+" else -1) * (hours * 60 + minutes)
        return cls.model_validate(parts)

    @staticmethod
    def native_second(value: datetime | time) -> Decimal:
        """Read native seconds and microseconds without applying the caller's Decimal precision."""
        coefficient = Decimal(value.second * 1_000_000 + value.microsecond)
        return DecimalValue.model_validate(coefficient).scaled(Decimal("0.000001"))

    @classmethod
    def from_value(cls, value: Value) -> Self | None:
        """Use native components without formatting and reparsing Python values."""
        match value:
            case TemporalValue():
                return cls.model_validate(value)
            case datetime():
                offset = value.utcoffset()
                return cls(
                    kind="DateTime",
                    year=value.year,
                    month=value.month,
                    day=value.day,
                    hour=value.hour,
                    minute=value.minute,
                    second=cls.native_second(value),
                    offset_minutes=int(offset.total_seconds() / 60) if offset is not None else None,
                )
            case date():
                return cls(kind="Date", year=value.year, month=value.month, day=value.day)
            case time():
                offset = value.utcoffset()
                return cls(
                    kind="Time",
                    hour=value.hour,
                    minute=value.minute,
                    second=cls.native_second(value),
                    offset_minutes=int(offset.total_seconds() / 60) if offset is not None else None,
                )
            case _:
                return None

    def native(self) -> date | time | Self:
        """Return a standard-library value only when no precision would be lost."""
        zone = timezone(timedelta(minutes=self.offset_minutes)) if self.offset_minutes is not None else None
        if self.kind == "Date" and self.year is not None and self.month is not None and self.day is not None:
            return date(self.year, self.month, self.day)
        if self.second is None:
            return self
        microseconds = DecimalValue.model_validate(self.second).scaled(Decimal(1_000_000))
        if microseconds != microseconds.to_integral_value():
            return self
        second = int(self.second)
        microsecond = int(microseconds) - second * 1_000_000
        if self.kind == "Time" and self.hour is not None and self.minute is not None:
            return time(self.hour, self.minute, second, microsecond, tzinfo=zone)
        if (
            self.kind == "DateTime"
            and self.year is not None
            and self.month is not None
            and self.day is not None
            and self.hour is not None
            and self.minute is not None
        ):
            return datetime(self.year, self.month, self.day, self.hour, self.minute, second, microsecond, tzinfo=zone)
        return self

    def shifted(self, quantity: QuantityValue, *, subtract: bool = False) -> date | time | Self:
        """Apply calendar arithmetic without adding precision to partial inputs."""
        unit = QuantityUnit.from_code(quantity.unit).arithmetic_unit()
        if unit is None:
            raise FHIRPathError("Temporal arithmetic requires a calendar duration or compatible fixed UCUM unit")
        if self.kind == "Time" and unit in {"year", "month", "week", "day"}:
            raise FHIRPathError("Time arithmetic requires hours, minutes, seconds or milliseconds")
        amount = quantity.value.copy_negate() if subtract else quantity.value
        if unit not in {"second", "millisecond"}:
            amount = Decimal(int(amount))
        if unit == "week":
            amount = DecimalValue.model_validate(amount).scaled(Decimal(7))
            unit = "day"
        precisions = ("year", "month", "day", "hour", "minute", "second")
        precision = precisions[(3 if self.kind == "Time" else 0) + len(self.components()) - 1]
        source_scale = QuantityUnit.from_code(unit).factor
        target_scale = QuantityUnit.from_code(precision).factor
        if source_scale < target_scale:
            conversion = DecimalValue.model_validate(amount)
            amount = (
                conversion.scaled(Decimal(1), Decimal(12))
                if precision == "year" and unit == "month"
                else conversion.scaled(source_scale, target_scale)
            )
            if precision != "second":
                amount = Decimal(int(amount))
            unit = precision
        try:
            anchor = datetime(self.year or 2000, self.month or 1, self.day or 1, self.hour or 0, self.minute or 0)
            second = self.second
            if unit in {"year", "month"}:
                months = int(amount) * (12 if unit == "year" else 1)
                year, month = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
                if not 1 <= year <= 9999:
                    raise FHIRPathError("Temporal arithmetic year is out of range")
                month += 1
                anchor = anchor.replace(year=year, month=month, day=min(anchor.day, monthrange(year, month)[1]))
            else:
                seconds = DecimalValue.model_validate(amount).scaled(QuantityUnit.from_code(unit).factor)
                if second is not None:
                    total = DecimalValue.model_validate(second).arithmetic("+", seconds)
                    minutes = int(
                        DecimalValue.model_validate(total)
                        .arithmetic("/", Decimal(60))
                        .to_integral_value(rounding=ROUND_FLOOR)
                    )
                    second = DecimalValue.model_validate(total).arithmetic("-", Decimal(minutes * 60))
                    anchor += timedelta(minutes=minutes)
                else:
                    anchor += timedelta(seconds=int(seconds))
        except (ValueError, OverflowError) as error:
            raise FHIRPathError("Temporal arithmetic is out of range") from error
        return type(self)(
            kind=self.kind,
            year=anchor.year if self.year is not None else None,
            month=anchor.month if self.month is not None else None,
            day=anchor.day if self.day is not None else None,
            hour=anchor.hour if self.hour is not None else None,
            minute=anchor.minute if self.minute is not None else None,
            second=second,
            offset_minutes=self.offset_minutes,
        ).native()

    def components(self) -> tuple[int | Decimal, ...]:
        """Normalize offsets at full precision, then retain only known components."""
        raw = (self.year, self.month, self.day, self.hour, self.minute, self.second)
        if self.kind == "Time":
            raw = raw[3:]
        components = tuple(value for value in raw if value is not None)
        if self.offset_minutes is None or self.hour is None:
            return components
        anchor = datetime(self.year or 2000, self.month or 1, self.day or 2, self.hour, self.minute or 0)
        adjusted = anchor - timedelta(minutes=self.offset_minutes)
        normalized: tuple[int | Decimal, ...] = (
            adjusted.year,
            adjusted.month,
            adjusted.day,
            adjusted.hour,
            adjusted.minute,
            self.second or Decimal(0),
        )
        if self.kind == "Time":
            normalized = normalized[3:]
        return normalized[: len(components)]

    def compare(self, other: Self) -> int | None:
        """Compare common precision; equal prefixes of different lengths are unknown."""
        if (self.kind == "Time") != (other.kind == "Time"):
            raise FHIRPathError("Time and date values cannot be compared")
        if (
            self.hour is not None
            and other.hour is not None
            and (self.offset_minutes is None) != (other.offset_minutes is None)
        ):
            return None
        left, right = self.components(), other.components()
        for a, b in zip(left, right, strict=False):
            if a != b:
                return (a > b) - (a < b)
        return 0 if len(left) == len(right) else None

    def equals(self, other: Self, *, equivalent: bool = False) -> bool | None:
        """Equivalence converts indeterminate precision equality into false."""
        if (self.kind == "Time") != (other.kind == "Time"):
            return False
        result = self.compare(other)
        return False if equivalent and result is None else None if result is None else result == 0

    @override
    def __str__(self) -> str:
        """Render precisely the components that were declared."""
        result = ""
        if self.year is not None:
            result = f"{self.year:04}"
        if self.month is not None:
            result += f"-{self.month:02}"
        if self.day is not None:
            result += f"-{self.day:02}"
        if self.kind == "DateTime":
            result += "T"
        if self.hour is not None:
            result += f"{self.hour:02}"
        if self.minute is not None:
            result += f":{self.minute:02}"
        if self.second is not None:
            seconds, point, fraction = format(self.second, "f").partition(".")
            result += ":" + seconds.zfill(2) + point + fraction
        if self.offset_minutes is not None:
            minutes = abs(self.offset_minutes)
            result += (
                "Z"
                if minutes == 0
                else f"{'+' if self.offset_minutes > 0 else '-'}{minutes // 60:02}:{minutes % 60:02}"
            )
        return result
