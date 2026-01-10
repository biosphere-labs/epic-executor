#!/bin/bash

set -e

# Clear pycache
find . -type d -name "__pycache__" -exec rm -r {} +

# Activate the virtual environment
source .venv/bin/activate

# Run the CLI
python -m epic_executor.cli "$@"
