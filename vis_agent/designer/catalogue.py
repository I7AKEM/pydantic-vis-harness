"""The chart catalogue, validated on load and shared with the designer's prompt."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from vis_agent.analyst.models import ColumnKind
from vis_agent.models import Intent

from .models import ChartType, Role


class RoleSpec(BaseModel):
    kinds: list[ColumnKind]
    required: bool = False


class Draw(BaseModel):
    type: str
    options: dict[str, Any] = {}


class CatalogueEntry(BaseModel):
    name: ChartType
    aliases: list[str] = []
    purposes: list[Intent]
    roles: dict[Role, RoleSpec]
    fields: dict[Role, str]
    rating: Literal["recommended", "caution", "fallback"]
    keys: list[str]
    category_min: int | None = None
    category_max: int | None = None
    group_max: int | None = None
    min_points: int | None = None
    min_rows: int | None = None
    additive_value: bool = False
    raw_values: bool = False
    draw: Draw
    summary: str


class Catalogue(BaseModel):
    entries: list[CatalogueEntry]

    def get(self, name: str) -> CatalogueEntry:
        """Return an entry by its canonical name, or raise KeyError."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise KeyError(name)

    def find(self, name_or_alias: str) -> CatalogueEntry | None:
        """Match a name or alias without case, accepting spaces in chart names."""
        name = name_or_alias.strip().casefold()
        for entry in self.entries:
            names = [entry.name, entry.name.replace("_", " "), *entry.aliases]
            if any(name == candidate.casefold() for candidate in names):
                return entry
        return None

    def describe(self) -> str:
        """Render one prompt line per entry with its purposes and binding needs."""
        lines = []
        for entry in self.entries:
            roles = ", ".join(
                f"{name} ({'/'.join(role.kinds)}; "
                f"{'required' if role.required else 'optional'})"
                for name, role in entry.roles.items()
            ) or "none; every column is shown"
            lines.append(
                f"{entry.name}: purposes={', '.join(entry.purposes)}; "
                f"roles={roles}; rating={entry.rating}; {entry.summary}"
            )
        return "\n".join(lines)


def load_catalogue() -> Catalogue:
    return Catalogue.model_validate_json(
        Path(__file__).with_name("catalogue.json").read_text(encoding="utf-8")
    )


CATALOGUE = load_catalogue()
