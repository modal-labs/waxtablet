# 📋 waxtablet

Waxtablet is an efficient, opinionated client for notebooks to interface with the [Language Server Protocol](https://microsoft.github.io/language-server-protocol/).

It handles document synchronization and request processing, so you can integrate LSP (e.g., [basedpyright](https://github.com/DetachHead/basedpyright) or [ty](https://github.com/astral-sh/ty)) into a remote notebook product, without needing to manually synchronize every document edit, which can be slow or tricky running over the network.

## Use cases

In a remote Jupyter kernel, the primary requests would be:

- `textDocument/hover`: Information about a symbol at a given line and character.
- `textDocument/completion`: Get a list of completions while typing.
- `textDocument/semanticTokens`: Compute semantic highlighting for a range of code.

While LSP has been designed for local IDEs, waxtablet stores its own internal representation of all the cells. The goal is to get diagnostics from a remote server without needing to literally buffer or send every keystroke.

## Example

```python
import waxtablet


# Initialize an empty notebook (default).
lsp = waxtablet.NotebookLsp(
    server=["basedpyright", "--stdio"],
    # server=["ty", "server"],
)
await lsp.start()

# Example usage
await lsp.add_cell("cell1", index=0, kind=waxtablet.CellKind.CODE)
await lsp.set_text("cell1", "print('Hello, world!')\ndic")
await lsp.hover("cell1", line=0, character=0)
await lsp.completion("cell1", line=1, character=3)

# Shutdown the server
await lsp.shutdown()
```

## License

Code is released under the [MIT License](LICENSE).
