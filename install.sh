#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
target_dir="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
timestamp="$(date +%Y%m%d-%H%M%S)"

if [[ "$repo_dir" == "$target_dir" ]]; then
    echo "Already installed at $target_dir"
    exit 0
fi

if [[ -L "$target_dir" ]]; then
    current_target="$(readlink -f -- "$target_dir")"
    if [[ "$current_target" == "$repo_dir" ]]; then
        echo "Symlink already points to $repo_dir"
        exit 0
    fi
    backup_dir="${target_dir}.backup-${timestamp}"
    mv -- "$target_dir" "$backup_dir"
    echo "Moved existing symlink to $backup_dir"
elif [[ -e "$target_dir" ]]; then
    backup_dir="${target_dir}.backup-${timestamp}"
    mv -- "$target_dir" "$backup_dir"
    echo "Moved existing config to $backup_dir"
fi

mkdir -p -- "$(dirname -- "$target_dir")"
ln -s -- "$repo_dir" "$target_dir"
echo "Linked $target_dir -> $repo_dir"
