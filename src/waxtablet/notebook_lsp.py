from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from enum import IntEnum
from pathlib import PurePosixPath
from typing import Any, Optional

from .types import CompletionItem, Hover, SemanticToken

logger = logging.getLogger(__name__)


def _cell_uri(nb_uri: str, cell_id: str) -> str:
    path = PurePosixPath(nb_uri.removeprefix("waxtablet-notebook://"))
    return f"waxtablet-notebook-cell://{path}#{cell_id}"  # NB: VSCode uses "vscode-notebook-cell://"


class CellKind(IntEnum):
    """Cell kinds for the LSP protocol."""

    MARKUP = 1  # A markup-cell is formatted source that is used for display.
    CODE = 2  # A code-cell is source code.


@dataclass(frozen=True)
class CellSync:
    """Cell synchronization information."""

    id: str
    kind: CellKind
    source: str | None = None  # Only synchronize source if not `None`


@dataclass
class Cell:
    id: str
    uri: str
    kind: CellKind
    text: str
    version: int


def lsp_locked(func):
    async def wrapper(self, *args, **kwargs):
        async with self._lock:
            return await func(self, *args, **kwargs)

    return wrapper


class NotebookLsp:
    _started: bool = False

    server: list[str]
    python_path: str
    workspace_folders: list[str]

    _proc: asyncio.subprocess.Process
    _reader_task: asyncio.Task
    _next_id: int
    _pending: dict[int, asyncio.Future]
    _lock: asyncio.Lock

    _cells: deque[Cell]
    _nb_uri: str
    _nb_version: int

    _semantic_tokens_legend: dict[str, list[str]]  # tokenTypes, tokenModifiers

    def __init__(
        self,
        *,
        server: list[str],
        python_path: str = sys.executable,
        workspace_folders: Optional[list[str]] = None,
    ) -> None:
        self.server = server
        self.python_path = python_path
        self.workspace_folders = workspace_folders or []

    async def start(self) -> None:
        if self._started:
            raise LspError("LSP server already started")

        self._proc = await asyncio.create_subprocess_exec(
            *self.server,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        self._next_id = 1
        self._pending = {}
        self._lock = asyncio.Lock()

        # background task to read server messages
        self._reader_task = asyncio.create_task(self._read_loop())

        self._cells = deque()
        self._nb_uri = "waxtablet-notebook:///notebook.ipynb"
        self._nb_version = 1

        self._started = True

        # send initialize / initialized
        initialize_resp: dict = await self._send(
            {
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": None,
                    "capabilities": {
                        "textDocument": {
                            "completion": {
                                "completionItem": {
                                    "documentationFormat": ["markdown", "plaintext"]
                                }
                            },
                            "hover": {
                                "contentFormat": ["markdown", "plaintext"],
                            },
                            # https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#semanticTokensClientCapabilities
                            "semanticTokens": {
                                "requests": {"full": True},
                                "tokenTypes": (
                                    "type class enum interface struct typeParameter parameter variable "
                                    "property enumMember event function method macro keyword modifier "
                                    "comment string number regexp operator decorator"
                                ).split(),
                                "tokenModifiers": (
                                    "declaration definition readonly static deprecated abstract async "
                                    "modification documentation defaultLibrary"
                                ).split(),
                                "formats": ["relative"],
                            },
                        },
                        "notebookDocument": {
                            "synchronization": {
                                "openClose": True,
                                "change": 1,  # TextDocumentSyncKind.Full
                            },
                        },
                    },
                    "initializationOptions": {
                        "pythonPath": self.python_path,
                    },
                    "workspaceFolders": [
                        {"uri": f"file://{folder}", "name": folder}
                        for folder in self.workspace_folders
                    ],
                },
            },
            as_request=True,
        )
        server_capabilities = initialize_resp.get("capabilities", {})
        self._semantic_tokens_legend = server_capabilities.get(
            "semanticTokensProvider", {}
        ).get("legend", {})

        await self._send({"method": "initialized", "params": {}})

        # open an empty notebook
        await self._send(
            {
                "method": "notebookDocument/didOpen",
                "params": {
                    "notebookDocument": {
                        "uri": self._nb_uri,
                        "notebookType": "jupyter-notebook",
                        "version": self._nb_version,
                        "cells": [],
                    },
                    "cellTextDocuments": [],
                },
            }
        )

    async def shutdown(self) -> None:
        if not self._started:
            return
        try:
            # polite shutdown
            await self._send({"method": "shutdown"}, as_request=True)
            await self._send({"method": "exit"})
        except Exception:
            pass
        finally:
            self._reader_task.cancel()
            self._proc.stdin.close()
            await self._proc.wait()
            self._started = False

    async def _did_change(self, **cells: dict) -> dict:
        """Boilerplate helper function for sending a didChange notification."""
        self._nb_version += 1
        return await self._send(
            {
                "method": "notebookDocument/didChange",
                "params": {
                    "notebookDocument": {
                        "uri": self._nb_uri,
                        "version": self._nb_version,
                    },
                    "change": {
                        # "metadata": {},
                        "cells": cells,
                    },
                },
            }
        )

    def _get_cell(self, cell_id: str) -> Optional[Cell]:
        """Get the Cell object for the given cell_id."""
        return next((c for c in self._cells if c.id == cell_id), None)

    def _get_cell_index(self, cell_id: str) -> int:
        """Get the index for the given cell_id."""
        return next((i for i, c in enumerate(self._cells) if c.id == cell_id), -1)

    @lsp_locked
    async def add_cell(self, cell_id: str, index: int, *, kind: CellKind) -> None:
        return await self._add_cell(cell_id, index, kind=kind)

    async def _add_cell(self, cell_id: str, index: int, *, kind: CellKind) -> None:
        """Insert a new empty cell at `index`."""
        index = max(0, min(len(self._cells), index))
        cell_uri = _cell_uri(self._nb_uri, cell_id)
        cell = Cell(id=cell_id, uri=cell_uri, kind=kind, text="", version=1)
        self._cells.insert(index, cell)  # local state
        await self._did_change(
            structure={
                "array": {
                    "start": index,
                    "deleteCount": 0,
                    "cells": [{"kind": kind, "document": cell_uri}],
                },
                "didOpen": [
                    {
                        "uri": cell_uri,
                        "languageId": "python" if kind == 2 else "markdown",
                        "version": cell.version,
                        "text": "",
                    }
                ],
            }
        )

    @lsp_locked
    async def move_cell(
        self, cell_id: str, new_index: int, *, new_kind: CellKind | None = None
    ) -> None:
        """Reorder an existing cell."""
        await self._move_cell(cell_id, new_index, new_kind=new_kind)

    async def _move_cell(
        self, cell_id: str, new_index: int, *, new_kind: CellKind | None = None
    ) -> None:
        old_index = self._get_cell_index(cell_id)
        if old_index == -1:
            return
        new_index = max(0, min(len(self._cells), new_index))
        cell = self._cells[old_index]
        del self._cells[old_index]
        if new_kind is not None:
            cell.kind = new_kind
        self._cells.insert(new_index, cell)
        await self._did_change(
            structure={"array": {"start": old_index, "deleteCount": 1, "cells": []}}
        )
        await self._did_change(
            structure={
                "array": {
                    "start": new_index,
                    "deleteCount": 0,
                    "cells": [{"kind": cell.kind, "document": cell.uri}],
                }
            }
        )

    @lsp_locked
    async def remove_cell(self, cell_id: str) -> None:
        """Remove an existing cell."""
        await self._remove_cell(cell_id)

    async def _remove_cell(self, cell_id: str) -> None:
        index = self._get_cell_index(cell_id)
        if index == -1:
            return
        del self._cells[index]
        await self._did_change(
            structure={"array": {"start": index, "deleteCount": 1, "cells": []}}
        )

    @lsp_locked
    async def set_text(self, cell_id: str, new_text: str) -> None:
        return await self._set_text(cell_id, new_text)

    async def _set_text(self, cell_id: str, new_text: str) -> None:
        cell = self._get_cell(cell_id)
        if cell is None or cell.text == new_text:
            return

        cell.version += 1
        cell.text = new_text

        await self._did_change(
            textContent=[
                {
                    "document": {"uri": cell.uri, "version": cell.version},
                    "changes": [
                        {
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 999999, "character": 0},
                            },
                            "text": new_text,
                        }
                    ],
                }
            ]
        )

    @lsp_locked
    async def synchronize_cells(self, cells: list[CellSync]) -> None:
        """Synchronize the order, values, and optionally contents of cells with the server."""
        new_cell_ids = {cell.id for cell in cells}

        # Remove cells that are no longer present.
        removed_cell_ids = [
            cell.id for cell in self._cells if cell.id not in new_cell_ids
        ]
        for cell_id in removed_cell_ids:
            await self._remove_cell(cell_id)

        # Move cells that have changed position, or add cells that are new.
        for i, new_cell in enumerate(cells):
            # Check if the cell is already present
            existing_index = self._get_cell_index(new_cell.id)
            if existing_index != -1:
                existing_cell = self._cells[existing_index]
                if existing_index != i or new_cell.kind != existing_cell.kind:
                    # Need to move the cell to this new position.
                    await self._move_cell(new_cell.id, i, new_kind=new_cell.kind)
            else:
                # Cell is not present, add a new cell
                await self._add_cell(new_cell.id, i, kind=new_cell.kind)

        # Edit any cell text that has changed.
        for new_cell in cells:
            if new_cell.source is not None:
                await self._set_text(new_cell.id, new_cell.source)

    @lsp_locked
    async def hover(
        self, cell_id: str, *, line: int, character: int
    ) -> Optional[Hover]:
        cell = self._get_cell(cell_id)
        if cell is None:
            return None
        result = await self._send(
            {
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": cell.uri},
                    "position": {"line": line, "character": character},
                },
            },
            as_request=True,
        )
        return Hover.parse(result) if result else None

    @lsp_locked
    async def completion(
        self,
        cell_id: str,
        *,
        line: int,
        character: int,
        context: Optional[dict] = None,
    ) -> Optional[list[CompletionItem]]:
        cell = self._get_cell(cell_id)
        if cell is None:
            return None
        result: dict = await self._send(
            {
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": cell.uri},
                    "position": {"line": line, "character": character},
                    "context": context or {},
                },
            },
            as_request=True,
        )
        if result is None:
            return None
        return [
            parsed
            for item in result.get("items", [])
            if (parsed := CompletionItem.parse(item))
        ]

    @lsp_locked
    async def semantic_tokens(self, cell_id: str) -> Optional[list[SemanticToken]]:
        cell = self._get_cell(cell_id)
        if cell is None:
            return None
        result: dict = await self._send(
            {
                "method": "textDocument/semanticTokens/full",
                "params": {
                    "textDocument": {"uri": cell.uri},
                },
            },
            as_request=True,
        )
        encoded_tokens: list[int] = result["data"]
        parsed: list[SemanticToken] = []
        line = 0
        start = 0
        for i in range(0, len(encoded_tokens), 5):
            delta_line, delta_start, length, token_type, token_modifiers = (
                encoded_tokens[i : i + 5]
            )
            line += delta_line
            if delta_line > 0:
                start = delta_start
            else:
                start += delta_start
            parsed_type = self._semantic_tokens_legend["tokenTypes"][token_type]
            modifiers = tuple(
                modifier
                for i, modifier in enumerate(
                    self._semantic_tokens_legend["tokenModifiers"]
                )
                if (1 << i) & token_modifiers
            )
            parsed.append(SemanticToken(line, start, length, parsed_type, modifiers))
        return parsed

    async def _send(self, msg: dict, *, as_request: bool = False) -> Any:
        """
        Send a notification or request.  When `as_request` is True,
        returns the server's result once the matching response arrives.
        """
        if as_request:
            msg_id = self._next_id
            self._next_id += 1
            msg["id"] = msg_id
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[msg_id] = fut
        else:
            msg_id = None

        raw = json.dumps({"jsonrpc": "2.0", **msg}, ensure_ascii=False)
        header = f"Content-Length: {len(raw.encode())}\r\n\r\n"
        self._proc.stdin.write(header.encode())
        self._proc.stdin.write(raw.encode())
        await self._proc.stdin.drain()

        if as_request:
            return await fut

    async def _read_loop(self) -> None:
        """
        Background task that parses server messages and
        resolves futures for requests.
        """
        reader = self._proc.stdout
        while True:
            header = await reader.readline()
            if not header:
                break  # server closed

            m = header.decode().rstrip().split(":", 1)
            if m[0].lower() != "content-length":
                continue  # ignore stray logs
            length = int(m[1])
            await reader.readline()  # empty line
            body = await reader.readexactly(length)
            msg = json.loads(body)

            if msg.get("method") == "window/logMessage":
                logger.info("[LSP] %s", msg["params"]["message"])
            elif msg.get("method") == "window/showMessage":
                logger.warning("[LSP] %s", msg["params"]["message"])
            elif "id" in msg and ("result" in msg or "error" in msg):
                fut = self._pending.pop(msg["id"], None)
                if fut:
                    if "result" in msg:
                        fut.set_result(msg["result"])
                    else:
                        fut.set_exception(LspError(json.dumps(msg["error"])))


class LspError(RuntimeError):
    """Exception raised for errors in LSP responses."""
