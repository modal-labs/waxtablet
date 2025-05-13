import asyncio

import waxtablet
from waxtablet.types import CompletionItem, Hover


def show_hover_output(hover: Hover | None) -> None:
    if hover is None:
        print("No hover information available.")
    else:
        print(f"hover info for {hover.range}")
        print(hover.contents.value)
    print("-" * 40)


def show_completion_output(completion: list[CompletionItem] | None) -> None:
    if completion is None:
        print("No completion information available.")
    else:
        for item in completion:
            print(f"[[[ Completion item: {item.label} ]]]")
            print(item)
            print()
    print("-" * 40)


async def main():
    lsp = waxtablet.NotebookLsp(
        server=["basedpyright-langserver", "--stdio"],
    )
    await lsp.start()

    # Example usage
    await lsp.add_cell("cell1", 0, kind=waxtablet.CellKind.CODE)
    await lsp.set_text("cell1", "print('Hello, world!')\ndic")
    show_hover_output(await lsp.hover("cell1", line=0, character=0))
    show_completion_output(await lsp.completion("cell1", line=1, character=3))

    print(await lsp.semantic_tokens("cell1"))

    # Clean up
    await lsp.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
