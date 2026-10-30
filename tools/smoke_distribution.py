"""Verify the built wheel's package surface and import it away from the checkout."""

from os import environ
from pathlib import Path
from subprocess import run
from sys import executable
from tempfile import TemporaryDirectory
from typing import Self
from zipfile import ZipFile

from pydantic import BaseModel


class DistributionSmoke(BaseModel):
    """The distribution and an isolated probe are the whole packaging contract."""

    wheel: Path
    probe: Path

    @classmethod
    def from_project(cls) -> Self:
        """Select the single built project wheel without relying on the current directory."""
        root = Path(__file__).resolve().parents[1]
        [wheel] = sorted((root / "dist").glob("fhirpath_pydantic-*.whl"))
        return cls.model_validate({"wheel": wheel, "probe": root / "tools/probe_distribution.py"})

    def check(self) -> None:
        """Verify required files and force the probe to import this wheel, not editable source."""
        with ZipFile(self.wheel) as archive:
            names = frozenset(archive.namelist())
            assert {
                "fhirpath_pydantic/__init__.py",
                "fhirpath_pydantic/py.typed",
                "fhirpath_pydantic/_grammar/FHIRPathLexer.py",
                "fhirpath_pydantic/_grammar/FHIRPathParser.py",
                "fhirpath_pydantic/_grammar/FHIRPathLexer.pyi",
                "fhirpath_pydantic/_grammar/FHIRPathParser.pyi",
            } <= names
            assert not any(name.startswith("fhirpathpy/") for name in names)
            [metadata] = [name for name in names if name.endswith(".dist-info/METADATA")]
            assert b"Requires-Dist: fhirpathpy" not in archive.read(metadata)
        with TemporaryDirectory() as directory:
            run(
                [executable, str(self.probe)],
                cwd=directory,
                env={**environ, "PYTHONPATH": str(self.wheel), "FHIRPATH_WHEEL": str(self.wheel)},
                check=True,
            )


if __name__ == "__main__":
    DistributionSmoke.from_project().check()
