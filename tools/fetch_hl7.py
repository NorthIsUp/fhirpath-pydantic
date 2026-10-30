"""Fetch the official HL7 corpora and all referenced inputs at one pinned revision."""

from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.request import urlretrieve
from xml.etree import ElementTree

from pydantic import BaseModel, Field

_REVISION = "db9fce391702b896c4e340dcb035ef44feb57093"
_ROOT = f"https://raw.githubusercontent.com/FHIR/fhir-test-cases/{_REVISION}"


class RepositoryEntry(BaseModel):
    """A Git tree entry supplies the exact corpus input path."""

    path: str
    type: str


class RepositoryTree(BaseModel):
    """A complete repository tree is required to resolve every referenced input."""

    tree: list[RepositoryEntry]
    truncated: bool

    def paths(self) -> set[str]:
        """Reject incomplete indexes instead of silently omitting data fixtures."""
        if self.truncated:
            raise ValueError("Official fixture repository tree was truncated")
        return {entry.path for entry in self.tree if entry.type == "blob"}


class SourceFile(BaseModel):
    """One unchanged upstream artifact and its recorded content digest."""

    local_path: str
    repository_path: str
    sha256: str

    @classmethod
    def from_remote(cls, repository_path: str, destination: Path) -> SourceFile:
        """Download an artifact from the pinned source and record its exact bytes."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(f"{_ROOT}/{repository_path}", destination)
        return cls(
            local_path=destination.as_posix(),
            repository_path=repository_path,
            sha256=sha256(destination.read_bytes()).hexdigest(),
        )


class CorpusFetch(BaseModel):
    """R4, R4B and R5 suites are downloaded in full without category filtering."""

    revision: str = _REVISION
    releases: tuple[Literal["r4", "r4b", "r5"], ...] = ("r4", "r4b", "r5")
    files: list[SourceFile] = Field(default_factory=list[SourceFile])

    def fetch(self) -> None:
        """Resolve each suite's declared inputs and persist provenance and licensing."""
        cache = Path(".cache/hl7-tree.json")
        cache.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(f"https://api.github.com/repos/FHIR/fhir-test-cases/git/trees/{self.revision}?recursive=1", cache)
        paths = RepositoryTree.model_validate_json(cache.read_bytes()).paths()
        self.files.append(SourceFile.from_remote("LICENSE.txt", Path("tests/hl7/LICENSE.txt")))
        for release in self.releases:
            suite = Path(f"tests/hl7/{release}/tests.xml")
            self.files.append(SourceFile.from_remote(f"{release}/fhirpath/tests-fhir-{release}.xml", suite))
            names = {
                name
                for case in ElementTree.parse(suite).getroot().iter()
                if case.tag.rsplit("}", 1)[-1] == "test" and (name := case.get("inputfile")) is not None
            }
            for name in sorted(names):
                if Path(name).name != name:
                    raise ValueError("Official corpus input names must be basenames")
                candidates = [path for path in paths if path.startswith(release + "/") and path.endswith("/" + name)]
                preferred = next(
                    (path for path in (f"{release}/{name}", f"{release}/examples/{name}") if path in candidates), None
                )
                if preferred is None and len(candidates) != 1:
                    raise ValueError(f"Cannot uniquely resolve {release}/{name}: {candidates}")
                self.files.append(
                    SourceFile.from_remote(preferred if preferred is not None else candidates[0], suite.parent / name)
                )
        Path("tests/hl7/sources.json").write_text(self.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    CorpusFetch().fetch()
