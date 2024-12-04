"""doc"""

from pathlib import Path

with (Path(__path__[0]) / "shapes_doc.md").open("r", encoding="utf-8") as f:
    SHAPES_DOC = f.read()
