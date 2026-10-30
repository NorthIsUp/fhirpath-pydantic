"""Regenerate the native grammar with a pinned, checksum-verified ANTLR release."""

from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from subprocess import run
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve

from pydantic import BaseModel


class GrammarGeneration(BaseModel):
    """The generator artifact and source grammar determine reproducible Python output."""

    jar: Path = Path(".cache/antlr-4.13.2-complete.jar")
    source: Path = Path("grammar/FHIRPath.g4")
    destination: Path = Path("src/fhirpath_pydantic/_grammar")

    def generate(self) -> None:
        """Verify the official generator and copy only Python runtime artifacts."""
        self.jar.parent.mkdir(parents=True, exist_ok=True)
        if not self.jar.exists():
            urlretrieve("https://www.antlr.org/download/antlr-4.13.2-complete.jar", self.jar)
        if (
            sha256(self.jar.read_bytes()).hexdigest()
            != "eae2dfa119a64327444672aff63e9ec35a20180dc5b8090b7a6ab85125df4d76"
        ):
            raise ValueError("ANTLR generator checksum mismatch")
        with TemporaryDirectory() as generated:
            run(
                [
                    "java",
                    "-jar",
                    str(self.jar),
                    "-Dlanguage=Python3",
                    "-no-listener",
                    "-Xexact-output-dir",
                    "-o",
                    generated,
                    str(self.source),
                ],
                check=True,
            )
            self.destination.mkdir(parents=True, exist_ok=True)
            for name in ("FHIRPathLexer.py", "FHIRPathParser.py"):
                copyfile(Path(generated) / name, self.destination / name)


if __name__ == "__main__":
    GrammarGeneration().generate()
