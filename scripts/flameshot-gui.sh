#!/usr/bin/env bash
set -u

export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-Hyprland}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
unset QT_SCALE_FACTOR
unset QT_ENABLE_HIGHDPI_SCALING
unset QT_SCREEN_SCALE_FACTORS
unset QT_AUTO_SCREEN_SCALE_FACTOR
unset QT_SCALE_FACTOR_ROUNDING_POLICY

if ! pgrep -x flameshot >/dev/null 2>&1; then
    flameshot >/tmp/flameshot-daemon.log 2>&1 &

    for _ in $(seq 1 30); do
        if dbus-send --session --dest=org.flameshot.Flameshot --print-reply / org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1; then
            break
        fi
        sleep 0.1
    done
fi

exec flameshot gui --delay 500
