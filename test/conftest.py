from __future__ import annotations

import pytest_asyncio
from typing import AsyncIterator

import waxtablet


@pytest_asyncio.fixture
async def lsp() -> AsyncIterator[waxtablet.NotebookLsp]:
    """Fresh NotebookLsp for each test that is shut down afterwards."""
    lsp = waxtablet.NotebookLsp(server=["basedpyright-langserver", "--stdio"])
    await lsp.start()
    try:
        yield lsp
    finally:
        await lsp.shutdown()
