import asyncio
from typing import Any

from waxtablet import NotebookLsp


def show_hover_output(hover: Any) -> None:
    if hover is None:
        print("No hover information available.")
    else:
        print(f"hover info for {hover['range']}")
        print(hover["contents"]["value"])


def show_completion_output(completion: Any) -> None:
    if completion is None:
        print("No completion information available.")
    else:
        for item in completion["items"]:
            print(f"[[[ Completion item: {item['label']} ]]]")
            print(item)


async def main():
    lsp = NotebookLsp()
    await lsp.open()

    # Example usage
    await lsp.add_cell("cell1", 0, kind=2)
    await lsp.set_text("cell1", "print('Hello, world!')\ndic")
    show_hover_output(await lsp.hover("cell1", line=0, character=0))
    show_completion_output(await lsp.completion("cell1", line=1, character=3))

    # Clean up
    await lsp.close()


if __name__ == "__main__":
    asyncio.run(main())
