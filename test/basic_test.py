import pytest

import waxtablet
from waxtablet.types import CompletionItem, Hover, SemanticToken


@pytest.mark.asyncio
async def test_hover_returns_info(lsp: waxtablet.NotebookLsp) -> None:
    await lsp.add_cell("cell_hover", 0, kind=waxtablet.CellKind.CODE)
    await lsp.set_text("cell_hover", "print('Hello, world!')\n")

    hover: Hover | None = await lsp.hover("cell_hover", line=0, character=0)

    assert hover is not None, "Expected hover information for built-in 'print'"
    assert "print" in hover.contents.value.lower()


@pytest.mark.asyncio
async def test_completion_suggests_dict(lsp: waxtablet.NotebookLsp) -> None:
    await lsp.add_cell("cell_completion", 0, kind=waxtablet.CellKind.CODE)
    await lsp.set_text("cell_completion", "dic")

    completions: list[CompletionItem] | None = await lsp.completion(
        "cell_completion", line=0, character=3
    )

    assert completions, "Expected at least one completion item"

    labels: set[str] = {item.label for item in completions}
    assert any(label.startswith("dict") for label in labels), (
        "Expected a completion suggestion starting with 'dict'"
    )


@pytest.mark.asyncio
async def test_semantic_tokens_identify_builtin_function(
    lsp: waxtablet.NotebookLsp,
) -> None:
    """
    The built-in function ``print`` should be reported as a semantic token with
    type ``function`` and the ``builtin`` and/or ``defaultLibrary`` modifiers.
    """
    await lsp.add_cell("cell_tokens", 0, kind=waxtablet.CellKind.CODE)
    await lsp.set_text("cell_tokens", "print('Hello, world!')\n")

    tokens: list[SemanticToken] = await lsp.semantic_tokens("cell_tokens")

    # Basic sanity check
    assert tokens, "Expected at least one semantic token"

    # Look for the token that represents the identifier ``print`` on line 0.
    print_token = next(
        (
            t
            for t in tokens
            if t.line == 0
            and t.start == 0
            and t.length == 5
            and t.token_type == "function"
        ),
        None,
    )
    assert print_token is not None, "No semantic token found for the 'print' call"

    # Check that the token is marked as a built-in / default-library symbol.
    modifiers = set(print_token.token_modifiers)
    assert {
        "builtin",
        "defaultLibrary",
    } & modifiers, "Expected 'builtin' or 'defaultLibrary' modifier on print()"
