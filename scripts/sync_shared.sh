#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Syncing shared modules..."
rm -rf "${SCRIPT_DIR}/../web/shared"
cp -R "${SCRIPT_DIR}/../shared" "${SCRIPT_DIR}/../web/shared"
rm -rf "${SCRIPT_DIR}/../chrome-extension/shared"
cp -R "${SCRIPT_DIR}/../shared" "${SCRIPT_DIR}/../chrome-extension/shared"
echo "Done."
