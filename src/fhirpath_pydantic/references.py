"""Call-local native reference indexing and contained-resource scope."""

from functools import cached_property
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from fhirpath_pydantic.native import NativeCollection, ResourceModel
from fhirpath_pydantic.types import Value


class ReferenceIndex(BaseModel):
    """An identity-preserving index created only within one evaluation."""

    by_reference: dict[str, BaseModel | None] = Field(default_factory=dict[str, BaseModel | None])
    containers: dict[int, ResourceModel] = Field(default_factory=dict[int, ResourceModel])

    def register(self, reference: str, resource: BaseModel) -> None:
        """Ambiguous relative references stay unresolved rather than choosing a resource."""
        if reference not in self.by_reference:
            self.by_reference[reference] = resource
        elif self.by_reference[reference] is not resource:
            self.by_reference[reference] = None

    @classmethod
    def from_resource(cls, root: Value) -> Self:
        """Index native Bundle entries and contained-resource ownership without dumping."""
        index = cls()
        pending = list(NativeCollection.from_value(root).root)
        seen: set[int] = set()
        while pending:
            item = pending.pop()
            if item.owner is None or id(item.value) in seen:
                continue
            resource = item.owner
            seen.add(id(resource))
            identifiers = NativeCollection.from_value(resource).member("id").values()
            if identifiers and isinstance(identifier := identifiers[0], str):
                index.register(f"{resource.__resource_type__}/{identifier}", resource)
            entries = NativeCollection.from_value(resource).member("entry")
            for entry in entries.root:
                resources = entry.member("resource")
                full_urls = entry.member("fullUrl").values()
                for child in resources.root:
                    if not isinstance(child.value, BaseModel):
                        continue
                    if full_urls and isinstance(full_url := full_urls[0], str):
                        index.register(full_url, child.value)
                    pending.append(child)
            for child in NativeCollection.from_value(resource).member("contained").root:
                if child.owner is not None:
                    index.containers[id(child.owner)] = resource
        return index

    def resolve(self, reference: str, owner: ResourceModel | None) -> BaseModel | None:
        """Contained references are relative to their containing resource, not the Bundle."""
        if not reference.startswith("#"):
            return self.by_reference.get(reference)
        if owner is None:
            return None
        container = self.containers.get(id(owner), owner)
        if reference == "#":
            return container
        matches = [
            item.value
            for item in NativeCollection.from_value(container).member("contained").root
            if isinstance(item.value, BaseModel) and item.member("id").values() == [reference[1:]]
        ]
        return matches[0] if len(matches) == 1 else None


class ResolutionScope(BaseModel):
    """A shared lazy index survives child-scope copies but never leaves an evaluation."""

    model_config = ConfigDict(frozen=True)
    resource: Value = None

    @cached_property
    def index(self) -> ReferenceIndex:
        """Build an index only if a query actually resolves references."""
        return ReferenceIndex.from_resource(self.resource)
