#!/bin/bash
# A quick click-to-run deployment script
echo "Deploying ForcedFocus..."
sudo bash "$(dirname "$0")/../install.sh"
echo "Deployment complete! You can close this window."
