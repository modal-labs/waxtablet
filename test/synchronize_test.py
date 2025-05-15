"""Tests for the synchronize_cells() method."""

import pytest

import waxtablet


@pytest.mark.asyncio
async def test_synchronize_cells(lsp: waxtablet.NotebookLsp) -> None:
    """Test the synchronize_cells() method."""
    # Add initial cells
    await lsp.add_cell("cell1", 0, kind=waxtablet.CellKind.CODE)
    await lsp.add_cell("cell2", 1, kind=waxtablet.CellKind.CODE)
    await lsp.set_text("cell1", "print('Hello, world!')\n")
    await lsp.set_text("cell2", "print('Goodbye, world!')\n")

    # Synchronize cells
    await lsp.synchronize_cells(
        [
            waxtablet.CellSync(
                id="cell2",
                kind=waxtablet.CellKind.CODE,
                source="print('Goodbye, world!')\n",
            ),
            waxtablet.CellSync(
                id="cell1",
                kind=waxtablet.CellKind.CODE,
                source="print('Hello, world!')\n",
            ),
        ]
    )

    # Check that the cells are still there, respond to hover events.
    assert await lsp.hover("cell1", line=0, character=0) is not None
    assert await lsp.hover("cell2", line=0, character=0) is not None

    # Try adding cell3 and removing cell2 via sync.
    await lsp.synchronize_cells(
        [
            waxtablet.CellSync(
                id="cell3",
                kind=waxtablet.CellKind.CODE,
                source="print('Hello, world!')\n",
            ),
            waxtablet.CellSync(id="cell1", kind=waxtablet.CellKind.CODE),
        ]
    )

    # Check that cell2 is gone, and cell3 is there.
    assert await lsp.hover("cell1", line=0, character=0) is not None
    assert await lsp.hover("cell3", line=0, character=0) is not None
    assert await lsp.hover("cell2", line=0, character=0) is None

    # Try changing cell1 to a markdown cell and reordering again.
    await lsp.synchronize_cells(
        [
            waxtablet.CellSync(id="cell3", kind=waxtablet.CellKind.CODE),
            waxtablet.CellSync(id="cell1", kind=waxtablet.CellKind.MARKUP),
        ]
    )

    # Check that cell3 is still there.
    assert await lsp.hover("cell3", line=0, character=0) is not None

    # Note: cell1 still responds to Python hover events, even as a Markdown cell in Pyright.
    # The client can just avoid sending LSP requests for Markdown cells, instead.
    #
    # assert await lsp.hover("cell1", line=0, character=0) is None
