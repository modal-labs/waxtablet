from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, Optional, TypeAlias

logger = logging.getLogger(__name__)

Json: TypeAlias = Dict[str, Any]


def _cell_uri(nb_uri: str, cell_id: str) -> str:
    path = PurePosixPath(nb_uri.removeprefix("waxtablet-notebook://"))
    return f"waxtablet-notebook-cell://{path}#{cell_id}"  # NB: VSCode uses "vscode-notebook-cell://"


@dataclass
class Cell:
    id: str
    uri: str
    kind: int  # 1 markdown, 2 code
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

    def __init__(
        self,
        *,
        server: list[str],
        python_path: str = sys.executable,
        workspace_folders: list[str] | None = None,
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
        await self._send(
            {
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": None,
                    "capabilities": {
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
            # await self._proc.wait()
            self._started = False

    async def _did_change(self, **cells: Json) -> Json:
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

    @lsp_locked
    async def add_cell(self, cell_id: str, index: int, *, kind: int) -> None:
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
    async def move_cell(self, cell_id: str, new_index: int) -> None:
        """Reorder an existing cell."""
        old_index = next((i for i, c in enumerate(self._cells) if c.id == cell_id), -1)
        if old_index == -1:
            return
        new_index = max(0, min(len(self._cells, new_index)))
        cell = self._cells[old_index]
        del self._cells[old_index]
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
        index = next((i for i, c in enumerate(self._cells) if c.id == cell_id), -1)
        if index == -1:
            return
        del self._cells[index]
        await self._did_change(
            structure={"array": {"start": index, "deleteCount": 1, "cells": []}}
        )

    @lsp_locked
    async def set_text(self, cell_id: str, new_text: str) -> None:
        cell = next((c for c in self._cells if c.id == cell_id), None)
        if cell is None:
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
    async def hover(self, cell_id: str, *, line: int, character: int) -> Json | None:
        cell = next((c for c in self._cells if c.id == cell_id), None)
        if cell is None:
            return None
        return await self._send(
            {
                "method": "textDocument/hover",
                "params": {
                    "textDocument": {"uri": cell.uri},
                    "position": {"line": line, "character": character},
                },
            },
            as_request=True,
        )

    @lsp_locked
    async def completion(
        self,
        cell_id: str,
        *,
        line: int,
        character: int,
        context: Optional[Json] = None,
    ) -> Json | None:
        cell = next((c for c in self._cells if c.id == cell_id), None)
        if cell is None:
            return None
        return await self._send(
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

    async def _send(self, msg: Json, *, as_request: bool = False) -> Any:
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
