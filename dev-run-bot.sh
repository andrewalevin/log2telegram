#!/bin/bash

#pip install -e . && ytb2audiobot --mode DEV
pip install -e . --no-deps

# Load the environment variables from the .env file, ignoring comments and handling special characters properly
set -a  # Automatically export all variables defined
source .env
set +a  # Disable automatic export

log2telegram
