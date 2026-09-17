#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
python3 -m unittest discover -s "$ROOT/work/tests" -p 'test_*.py' -v
bash -n "$ROOT/work/scripts/benchmark_llama_backend.sh"
python3 -m py_compile \
  "$ROOT/work/scripts/bench_client.py" \
  "$ROOT/work/scripts/resource_sampler.py"
