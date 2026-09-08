"""Material Maker MCP server package.

Lets an MCP client author Material Maker node graphs, validate them against a
catalog built from the app's own node definitions, and render them through a native graphics context
to PBR texture maps. Units:
  catalog_builder.py  build catalog.json from the .mmg node definitions
  graph.py            pure .ptex graph helpers (find material node, isolate node output)
  validator.py        validate a graph against the catalog
  render.py           headless Godot render runner
  overlay.py          build/refresh the live-control addon overlay (disposable working copy)
  paths.py            client-path guards (allowed-roots bounding, traversal rejection)
  inspect.py          read-only .ptex metrics (for the inspect_project tool)
  server.py           legacy authoring/live tools and catalog + guide resources
  tools.py            shared project, recipe, build and job MCP adapters
"""

from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("mm-mcp")
except PackageNotFoundError:  # not pip-installed (tests import via pythonpath=src)
    __version__ = "0.8.0a1"

# Upstream Material Maker revision every cookbook graph was authored against.
# `mm-mcp --check` prints the local checkout's sha beside it. The portable CI
# gate does not clone or run Material Maker; native acceptance is a separate
# operator-configured check. Bump deliberately, then regenerate the cookbook
# and run quality/promote_cookbook.py --check against that native checkout.
MM_UPSTREAM_PIN = "ad19fcf0ee34a7caf74df709dc4de7112f0d467d"  # full sha: GitHub only serves fetch-by-sha for full ids
