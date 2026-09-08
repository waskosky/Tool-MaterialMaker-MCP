# Archive execution evidence

These files came from the supplied archive and describe its original run, before
local integration fixes. Current checks are recorded separately in
[INTEGRATION.md](../docs/upgrade/INTEGRATION.md).

`execution-summary.json` is the archive's verification-scope summary. `release-gate.log` and the XML report record its 218 passed / 3 skipped gate. The browser screenshot shows a deliberately synthetic test material and the unavailable-WebGL fallback; it is not native artwork or three-dimensional shading evidence. Historical collection/network logs document limitations, not passing certification. That wheel installation used `--no-deps` solely to verify packaging; the real MCP dependency was absent in the archive's environment.

Copied text logs normalize trailing whitespace; test results and XML are unchanged.
