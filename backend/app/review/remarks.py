"""What every check returns: remarks the author reads, each pointing at places in the book."""

from pydantic import BaseModel


class Place(BaseModel):
    chapter_id: str
    chapter_title: str
    paragraph: int | None = None
    quote: str


class Remark(BaseModel):
    category: str
    problem: str
    suggestion: str = ""
    places: list[Place]
    # Set for typesetting remarks: "Fix all" corrects them without a model.
    fixable: bool = False
