# Security and permission boundaries

## Threat model

This is an authenticated local creative tool for a trusted operator, not a service
for mutually untrusted tenants. AI requests, imported graphs, file paths and stale
client state can be incorrect or hostile. Native shaders, native export templates
and operator-installed Material Maker code are privileged executable dependencies.

## Implemented protections

The browser binds loopback only, requires a random session token on API calls,
validates Host/Origin and cross-site request metadata, and does not enable CORS.
Responses use a restrictive local-content policy and no-referrer/no-store headers.
Requests are bounded to 8 MiB, including duplicate/non-finite JSON rejection; server
concurrency is capped at 24 request threads. Static and build paths reject traversal
and symlink escapes.

Native discovery contains a token and protocol identifier, written privately on
supported Unix systems. The Python client refuses insecure discovery permissions,
unknown endpoints and oversized messages. The Godot bridge binds only loopback,
authenticates requests and bounds peer/payload lifetime. Windows user-directory and
filesystem access controls remain an operating-system prerequisite, not something
this package can claim to audit completely.

New inline shaders and custom export code are disabled unless the operator permits
them. Cookbook graph code can be reused through service-owned provenance and exact
approved-definition hashes; editing that code does not inherit approval. Do not
interpret an agent-supplied `trusted` flag as authority—no such public authorization
switch is provided on the build interface.

Personal recipes preserve existing approval in service-owned
`provenance/recipes/` records, separate from editable recipe metadata. Approval
covers inline shader definitions and both custom-script fields. Metadata supplied
by a caller cannot grant approval to new code.

Recognized external file parameters are resolved to existing approved local files
or native `res://` resources and recorded by hash. Relative ambiguous paths and
unsupported URI schemes are rejected. Legacy source saving cannot write managed
workspace state or metadata. No public endpoint executes an arbitrary shell command.

Workspace edits validate a complete candidate before committing. Revision checks
protect against accidental concurrent overwrites; named recovery and history support
reversal. Native writes have an additional experimental gate and separate recovery
files. Cancellation targets worker-owned processes, not an attached artist's editor.

## Explicit limits

These controls are not an operating-system sandbox and are not a complete interpreter
for every future Material Maker node's file-access behavior. Trust operator-installed
node definitions and exports. Run unknown code in an isolated low-privilege machine
or account with filesystem/network restrictions. Do not enable custom code merely
to make a validation warning disappear.

A process that can rewrite the workspace can also rewrite provenance or manifests.
Hashes detect ordinary corruption, not a malicious administrator. Do not put untrusted
assets or secrets in the same broadly approved root. Keep render workspaces distinct
from source control credentials and personal documents.

History and completed builds consume disk until the operator archives/removes them.
There is no global disk quota, tenancy system, request billing, remote authentication
provider or complete service-denial guarantee. Large native graphs can exhaust graphics
memory or trigger driver faults despite structural validation. Start at small
resolutions; enforce OS resource limits for automation workers.

The renderer/source fingerprints do not promise cross-device pixel identity. External
assets are not automatically copied into exports, and a dependency's license is not
inferred from its path. Personal recipe publication is application-atomic under a
cooperating lock; it is not protection against an adversary with direct filesystem access.

Native global undo, graphics-resource lifetime after unusual engine exceptions,
manual tab changes during rendering, and export-metadata effects on native revisions
must pass local acceptance. Until then keep `MM_ENABLE_EXPERIMENTAL_LIVE_WRITES=0`.
