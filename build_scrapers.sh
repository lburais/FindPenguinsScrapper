#!/bin/sh

# brew install rust
# curl https://github.com/ofek/pyapp/releases/latest/download/source.tar.gz -Lo pyapp-source.tar.gz
# tar -xzf pyapp-source.tar.gz
# mv pyapp-v* pyapp
# cd pyapp

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd pyapp
WHEEL="${1:-$PROJECT_DIR/dist/scrapers-0.1.0-py3-none-any.whl}"
mkdir -p executables
PYAPP_PROJECT_PATH="$WHEEL" \
PYAPP_EXEC_SPEC="scrapers:main" \
PYAPP_PYTHON_VERSION=3.12 \
PYAPP_EXPOSE_PYTHON=1 \
CARGO_TARGET_DIR="target-scrapers" \
  cargo build --release
cp "target-scrapers/release/pyapp" "executables/scrapers"
