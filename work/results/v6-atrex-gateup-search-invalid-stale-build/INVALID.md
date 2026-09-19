# INVALID — stale plugin backend

These two dry-run records are retained as evaluator-regression evidence only.
The candidate and control backend SHA-256 values are identical
(`40f6b9c...b25b40`) because the original evaluator built
`test-backend-ops` but not the separately loaded `ggml-rocmfpx-vulkan`
target. Consequently, neither reported delta measures BK_STEP=1 or BK_STEP=3.

The evaluator was corrected in root commit `f8e58a3`: it now builds the plugin
target explicitly and fails closed whenever a patched candidate has the same
backend hash as control. Do not use the `PASS`/decision fields inside the raw
pre-fix result JSON files.
