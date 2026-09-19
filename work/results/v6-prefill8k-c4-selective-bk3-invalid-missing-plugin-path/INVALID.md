# INVALID — Charlie plugin path missing

This second harness attempt exported the direct backend path used by
`test-backend-ops`, but not `ROCMFPX_PLUGIN_PATH`. `llama-server` therefore
rejected `ROCmFPXVulkan0` before serving a request. It contains no performance
result.

The corrected runner exports the absolute path to
`rocmfpx-vulkan-plugin.so` and requires `llama-server --list-devices` to report
`ROCmFPXVulkan0` both before and after the candidate build. The production
backend was restored to SHA-256 `40f6b9c...b25b40`.
