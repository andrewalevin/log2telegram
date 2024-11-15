#!/bin/bash

#pip install -e . && ytb2audiobot --mode DEV
pip install -e . --no-deps

log2telegram --filter-color-chars --filter-timestamps /Users/andrewlevin/Desktop/ytb2audiobot/output.log

# log2telegram exp.txt