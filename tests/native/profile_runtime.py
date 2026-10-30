"""Profile compiled native traversal on a synthetic resource via mise run profile."""

from cProfile import Profile
from pstats import SortKey, Stats

from fhir.resources.patient import Patient
from pydantic import BaseModel, Field

from fhirpath_pydantic import compile


class ProfileRun(BaseModel):
    """A reproducible synthetic workload for locating native evaluation costs."""

    names: int = Field(default=1000, gt=0)
    iterations: int = Field(default=25, gt=0)

    def run(self) -> None:
        """Measure evaluation after warming the syntax and model metadata caches."""
        resource = Patient.model_validate({"name": [{"use": "official", "given": ["benchmark"]}] * self.names})
        query = compile("Patient.name.where(use = 'official').given.first()", output_type=str)
        assert query(resource) == ["benchmark"]
        with Profile() as profile:
            for _ in range(self.iterations):
                assert query(resource) == ["benchmark"]
        Stats(profile).strip_dirs().sort_stats(SortKey.CUMULATIVE).print_stats(25)


if __name__ == "__main__":
    ProfileRun().run()
