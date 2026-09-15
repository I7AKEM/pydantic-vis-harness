"""A finding: one problem an agent names, at one of two levels, owned by whoever can fix it. The team's shared word."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["error", "warning"]
Owner = Literal["analyst", "designer", "renderer", "user", "none"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str = Field(description="The rule's id: R-1 to R-5 for the reviewer's own rules, or an id from the team's "
                                  "lists, such as S5, C4, or time_in_order.")
    level: Level = Field(description="error: the chart is wrong or misleads; warning: it reads worse.")
    owner: Owner = Field(description="Who can fix it: designer for the spec, analyst for the table, renderer for the "
                                     "drawing, user for a decision only the caller can make, none when nothing can.")
    message: str = Field(description="What is wrong, in the caller's language, naming the mark, label, or number.")
