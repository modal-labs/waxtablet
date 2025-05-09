# 📋 waxtablet

Waxtablet is a simple, opinionated client for notebooks to interface with the [Language Server Protocol](https://microsoft.github.io/language-server-protocol/).

It handles document synchronization and request processing, so you can integrate LSP (e.g., [basedpyright](https://github.com/DetachHead/basedpyright) or [ty](https://github.com/astral-sh/ty)) into a remote notebook product, without needing to manually synchronize every document edit, which can be slow or tricky running over the network.

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
await lsp.add_cell("cell1", index=0, kind=waxtablet.CellKind.PYTHON)
await lsp.set_text("cell1", "print('Hello, world!')\ndic")
await lsp.hover("cell1", line=0, character=0)
await lsp.completion("cell1", line=1, character=3)

# Shutdown the server
await lsp.shutdown()
```

## License

Code is released under the [MIT License](LICENSE).
