WHEEL="/Volumes/Ra/Development/scrapers/dist/scrapers-0.1.0-py3-none-any.whl"
mkdir -p executables
for command in findpenguins aventures2rst reminder reminders2rst; do
  PYAPP_PROJECT_PATH="$WHEEL" \
  PYAPP_EXEC_SPEC="$command:main" \
  PYAPP_PYTHON_VERSION=3.12 \
  PYAPP_EXPOSE_PYTHON=1 \
  CARGO_TARGET_DIR="target-$command" \
    cargo build --release || exit 1
  cp "target-$command/release/pyapp" "executables/$command"
done
