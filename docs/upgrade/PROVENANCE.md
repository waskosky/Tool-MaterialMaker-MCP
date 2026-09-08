# Provenance and primary implementation references

## Inputs

The baseline is the user's uploaded `Tool-MaterialMaker-MCP-main.zip`, identified in
the earlier review as 0.7.0 at commit `b41b65c612557a7da35a045091199058c0f76abb`.
The original README, license, cookbook and historical development records were retained.
SHA-256 checksums and the exact changed-file inventory accompany the delivery.

The implementation is a local proposed 0.8.0a1 branch. No change was pushed to a remote
repository. No MaterialPilot source file was incorporated. The existing native
compatibility pin remains `ad19fcf0ee34a7caf74df709dc4de7112f0d467d`.

## Sources checked for contracts

- Material Maker `addons/material_maker/engine/nodes/gen_material.gd`: `export_material`
  takes a pixel size, not a logarithmic exponent. It accepts the profile and command-line flag.
- Material Maker `addons/material_maker/nodes/material.mmg`: canonical output channel
  names, connected-channel conditions and packed occlusion/roughness/metallic profile.
- Material Maker `addons/material_maker/engine/nodes/gen_base.gd`: integer seed
  serialization uses `seed_int`, with the native seed conversion defined by MAX_SEED.
- Official MCP Python SDK `src/mcp/server/mcpserver/utilities/types.py`: image results
  can use `Image(data=..., format='png')`. The actual SDK was not executed here.
- Official three.js material documentation: packed-map channel assignments, color/data
  distinction, second texture-coordinate set for occlusion and normal-map precedence
  over bump mapping. The bundled viewer remains on its existing r128 API; it uses that
  version's encoding properties rather than silently mixing in current-version APIs.

Primary locations:

- https://github.com/RodZill4/material-maker
- https://github.com/modelcontextprotocol/python-sdk
- https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- https://threejs.org/docs/pages/MeshStandardMaterial.html

The online sources were consulted on September 8, 2026. Native/API implementation
reference reads do not establish that the entire updated package runs under those
tools; the acceptance procedures and unverified boundaries are recorded separately.

## Third-party components

The existing three.js bundle and other original vendor content are retained with
existing notices. The cookbook is copied into wheel package data as a synchronized
resource, not replaced by generated imitations. Material Maker and Godot binaries,
font files, private credentials, runtime tokens and native source checkouts are not
included in this delivery.
