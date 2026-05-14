#!/bin/bash
echo "Syncing shared modules..."
cp -R shared web/shared
cp -R shared chrome-extension/shared
echo "Done."
