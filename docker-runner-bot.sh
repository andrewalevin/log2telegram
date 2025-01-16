#!/bin/bash

# Docker runner script with production-grade checks.

set -euo pipefail  # Exit immediately if a command fails, unset variable is used, or a pipeline fails.

# Function to log messages with timestamps
log_message() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_message "🐳 Starting Docker container..."

# Check if required environment variables are set
if [[ -z "${L2T_PATH:-}" ]]; then
    log_message "❌ Environment variable 'L2T_PATH' is not set. Exiting."
    exit 1
fi

if [[ ! -f "$L2T_PATH" ]]; then
    log_message "⚠️ Log file '$L2T_PATH' does not exist. Creating it..."
    touch "$L2T_PATH"
fi

if [[ ! -w "$L2T_PATH" ]]; then
    log_message "❌ Log file '$L2T_PATH' is not writable. Exiting."
    exit 1
fi

# Ensure the log2telegram command is available
if ! command -v log2telegram &> /dev/null; then
    log_message "❌ 'log2telegram' command is not found. Make sure it is installed and in the PATH. Exiting."
    exit 1
fi

# Run the log2telegram command
VERSION=$(pip show log2telegram | grep Version )
log_message "🔄 Running log2telegram ('$VERSION') with  path '$L2T_PATH'..."
log2telegram "$L2T_PATH"

log_message "✅ Docker container setup complete."