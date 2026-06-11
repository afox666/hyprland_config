# Hyprland config

Personal Hyprland configuration and helper scripts.

## Contents

- `hyprland.lua` - Hyprland Lua config.
- `hypridle.conf` - idle/lock policy.
- `hyprlock.conf` - lock screen config.
- `waybar/` - Waybar bar and tray config.
- `scripts/` - helper scripts for lock, idle, screenshot, scratchpad, and workspace corner scrolling.

## Dependencies

Install the pieces you use on the target machine:

- Hyprland with Lua config support
- `hyprlock`, `hypridle`, `hyprctl`
- `waybar`
- `nm-applet`
- `ghostty`, `dolphin`, `rofi`
- `wpctl`, `brightnessctl`, `playerctl`
- `flameshot`
- `jq`
- Python 3 with PyGObject/GTK 3
- `gtk-layer-shell`

Package names vary by distribution. On Arch-based systems, the Python/GTK layer usually comes from packages such as `python-gobject`, `gtk3`, and `gtk-layer-shell`.

## Install on a new machine

Clone this repository, then run:

```sh
./install.sh
```

The installer backs up an existing real `~/.config/hypr` directory, then creates a symlink from `~/.config/hypr` to this repository. The config uses `$HOME/.config/hypr/scripts/...`, so the symlinked layout is expected.

If this repository already lives at `~/.config/hypr`, no symlink is needed.

## After changing config

```sh
git status
git add .
git commit -m "Update Hyprland config"
```
