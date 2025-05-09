# Development

Install `uv` and, then you can run tests:

```bash
uv run pytest
```

There are some scripts in the `examples/` folder that can be run with `uv run`.

## Publishing

```bash
uv build
uv run hatch publish

VERSION=$(uv version | awk '{ print $2 }')
git tag $VERSION
git push --tags
```
