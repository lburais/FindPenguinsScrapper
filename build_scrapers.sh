#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WHEEL="${1:-$PROJECT_DIR/dist/scrapers-0.1.0-py3-none-any.whl}"
mkdir -p executables
PYAPP_PROJECT_PATH="$WHEEL" \
PYAPP_EXEC_SPEC="scrapers:main" \
PYAPP_PYTHON_VERSION=3.12 \
PYAPP_EXPOSE_PYTHON=1 \
CARGO_TARGET_DIR="target-scrapers" \
  cargo build --release
cp "target-scrapers/release/pyapp" "executables/scrapers"
