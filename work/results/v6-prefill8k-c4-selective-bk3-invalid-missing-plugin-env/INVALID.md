# INVALID — plugin registration environment missing

This run failed before any request was measured. The first server process did
not inherit `ROCMFPX_BACKEND_PATH` and the required C++ runtime preload, so
`ROCmFPXVulkan0` was not registered and `-dev ROCmFPXVulkan0` was rejected.

The benchmark wrapper now exports both variables explicitly. No throughput,
TTFT, output or quality conclusion may be drawn from this directory. The
cleanup path restored the production backend SHA-256
`40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.
