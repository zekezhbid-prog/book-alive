"""Whether a picture the user puts in as it is matches the project style. The service keeps
every picture of a project in one style, so a picture in another one is refused, not redrawn."""

import base64

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.llm.calls import TextModel

SYSTEM = """You compare a picture with the visual style of an illustrated book.
Judge only the drawing style: medium (photo, 3D render, oil, watercolour, ink, anime, pixel
art...), rendering, palette and level of detail. Ignore the subject, pose, background and
picture quality. A picture in the same medium and close in look matches even if details differ.
Reply with only a JSON object: {"matches": true or false, "reason": "..."} where reason is one
short sentence in Russian naming the picture's style and, if it does not match, the difference."""


class StyleVerdict(BaseModel):
    matches: bool
    reason: str = ""


def check_style(model: TextModel, style: str, data: bytes, mime: str) -> StyleVerdict:
    encoded = base64.b64encode(data).decode()
    message = HumanMessage(
        content=[
            {"type": "text", "text": f"The book's style: {style}"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]
    )
    return model.invoke_json("style_check", [SystemMessage(SYSTEM), message], StyleVerdict)
