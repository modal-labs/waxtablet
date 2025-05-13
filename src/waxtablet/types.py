from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class MarkupKind(Enum):
    TEXT = "plaintext"
    MARKDOWN = "markdown"


@dataclass(frozen=True)
class MarkupContent:
    kind: MarkupKind
    value: str

    @classmethod
    def parse(cls, obj: dict) -> MarkupContent | None:
        try:
            return cls(kind=obj["kind"], value=obj["value"])
        except (KeyError, TypeError):
            return None


@dataclass(frozen=True)
class Position:
    line: int
    character: int

    def __str__(self) -> str:
        return f"{self.line}:{self.character}"

    @classmethod
    def parse(cls, obj: dict) -> Position | None:
        try:
            return cls(line=obj["line"], character=obj["character"])
        except (KeyError, TypeError):
            return None


@dataclass(frozen=True)
class Range:
    start: Position
    end: Position

    def __str__(self) -> str:
        return f"{self.start}..{self.end}"

    @classmethod
    def parse(cls, obj: dict) -> Range | None:
        try:
            return cls(
                start=Position.parse(obj["start"]),
                end=Position.parse(obj["end"]),
            )
        except (KeyError, TypeError):
            return None


@dataclass(frozen=True)
class TextEdit:
    range: Range
    new_text: str

    @classmethod
    def parse(cls, obj: dict) -> TextEdit | None:
        try:
            return cls(range=Range.parse(obj["range"]), new_text=obj["newText"])
        except (KeyError, TypeError):
            return None


## Hover


@dataclass(frozen=True)
class Hover:
    contents: MarkupContent
    range: Range | None = None

    @classmethod
    def parse(cls, obj: dict) -> Hover | None:
        try:
            return cls(
                contents=MarkupContent.parse(obj["contents"]),
                range=Range.parse(obj["range"]) if "range" in obj else None,
            )
        except (KeyError, TypeError):
            return None


## Completion


class CompletionItemKind(IntEnum):
    TEXT = 1
    METHOD = 2
    FUNCTION = 3
    CONSTRUCTOR = 4
    FIELD = 5
    VARIABLE = 6
    CLASS = 7
    INTERFACE = 8
    MODULE = 9
    PROPERTY = 10
    UNIT = 11
    VALUE = 12
    ENUM = 13
    KEYWORD = 14
    SNIPPET = 15
    COLOR = 16
    FILE = 17
    REFERENCE = 18
    FOLDER = 19
    ENUM_MEMBER = 20
    CONSTANT = 21
    STRUCT = 22
    EVENT = 23
    OPERATOR = 24
    TYPE_PARAMETER = 25


@dataclass(frozen=True)
class CompletionItemLabelDetails:
    detail: str | None = None
    description: str | None = None

    @classmethod
    def parse(cls, obj: dict) -> CompletionItemLabelDetails | None:
        try:
            return cls(detail=obj.get("detail"), description=obj.get("description"))
        except (KeyError, TypeError):
            return None


@dataclass(frozen=True)
class CompletionItem:
    label: str
    label_details: CompletionItemLabelDetails | None = None
    kind: CompletionItemKind | None = None
    detail: str | None = None
    sort_text: str | None = None
    filter_text: str | None = None
    documentation: str | MarkupContent | None = None
    text_edit: TextEdit | None = None
    additional_text_edits: tuple[TextEdit, ...] = ()

    @classmethod
    def parse(cls, obj: dict) -> CompletionItem | None:
        try:
            return cls(
                label=obj["label"],
                label_details=CompletionItemLabelDetails.parse(
                    obj.get("labelDetails", {})
                ),
                kind=CompletionItemKind(obj["kind"]) if "kind" in obj else None,
                detail=obj.get("detail"),
                sort_text=obj.get("sortText"),
                filter_text=obj.get("filterText"),
                documentation=MarkupContent.parse(obj.get("documentation", {})),
                text_edit=TextEdit.parse(obj.get("textEdit", {})),
                additional_text_edits=tuple(
                    TextEdit.parse(edit) for edit in obj.get("additionalTextEdits", [])
                ),
            )
        except (KeyError, TypeError):
            return None


## Semantic Tokens


@dataclass(frozen=True)
class SemanticToken:
    # These are decoded from relative-positioned integers with a legend.
    # https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_semanticTokens
    line: str
    start: int
    length: int
    token_type: str
    token_modifiers: tuple[str, ...] = ()
