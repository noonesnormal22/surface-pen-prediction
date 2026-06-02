#!/bin/bash
# Builds pen_prediction-krita-docker.zip from plugin source.
# Run this after making changes to the plugin before installing.
set -e
cd "$(dirname "$0")/plugin"
rm -f ../pen_prediction-krita-docker.zip
zip -r ../pen_prediction-krita-docker.zip pen_prediction.desktop pen_prediction/
echo "Built: pen_prediction-krita-docker.zip"
echo "Install via Krita → Tools → Scripts → Import Python Plugin from File"
