#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Source this script so it can activate the virtualenv:"
    echo "  source ./init.sh"
    exit 1
fi

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || return 1
cd "$repo_dir" || return 1
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    if ! command -v curl >/dev/null 2>&1; then
        echo "curl is required to install uv" >&2
        return 1
    fi

    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh || return 1
    hash -r
fi

echo "Syncing project environment..."
uv sync || return 1

# shellcheck disable=SC1091
source .venv/bin/activate || return 1

echo
echo "Environment ready."
echo "Use 'inv --list' or 'uv run inv --list' to see available tasks."
