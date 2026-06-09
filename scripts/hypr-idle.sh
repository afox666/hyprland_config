#!/usr/bin/env bash
set -euo pipefail

if pidof hypridle >/dev/null 2>&1; then
    exit 0
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    HYPRLAND_INSTANCE_SIGNATURE=$(
        find "$XDG_RUNTIME_DIR/hypr" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' 2>/dev/null \
            | sort -n \
            | tail -1 \
            | awk '{print $2}'
    )
    export HYPRLAND_INSTANCE_SIGNATURE
fi

if [[ -z "${WAYLAND_DISPLAY:-}" && -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    wayland_display="$(sed -n '2p' "$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/hyprland.lock" 2>/dev/null || true)"
    if [[ -n "$wayland_display" ]]; then
        export WAYLAND_DISPLAY="$wayland_display"
    fi
fi

exec hypridle
