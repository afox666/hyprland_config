#!/usr/bin/env bash
set -euo pipefail

scratch_name="scratch"
state_file="${XDG_RUNTIME_DIR:-/tmp}/hypr-scratchpad-stack"

ensure_hypr_env() {
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
}

hypr() {
    ensure_hypr_env
    hyprctl "$@"
}

lua_dispatch() {
    hypr dispatch "$1" >/dev/null
}

active_window_json() {
    hypr activewindow -j
}

current_workspace_name() {
    hypr activeworkspace -j | jq -r '.name'
}

scratch_size() {
    hypr monitors -j | jq -r '
        map(select(.focused == true))[0] // .[0]
        | "\(((.width / .scale) * 0.75) | floor) \(((.height / .scale) * 0.80) | floor)"
    '
}

window_exists() {
    local address="$1"
    hypr clients -j | jq -e --arg address "$address" '.[] | select(.address == $address)' >/dev/null
}

stack_push() {
    local record="$1"
    mkdir -p "$(dirname "$state_file")"
    printf '%s\n' "$record" >> "$state_file"
}

stack_pop_existing() {
    [[ -f "$state_file" ]] || return 1

    local tmp record address
    tmp="$(mktemp)"

    tac "$state_file" | while IFS= read -r record; do
        address="${record%%|*}"
        if window_exists "$address"; then
            printf '%s\n' "$record"
            break
        fi
    done > "$tmp"

    if [[ ! -s "$tmp" ]]; then
        : > "$state_file"
        rm -f "$tmp"
        return 1
    fi

    record="$(cat "$tmp")"
    rm -f "$tmp"

    grep -Fvx "$record" "$state_file" > "${state_file}.new" || true
    mv "${state_file}.new" "$state_file"
    printf '%s\n' "$record"
}

push_active() {
    local window address workspace floating width height
    window="$(active_window_json)"
    address="$(jq -r '.address // empty' <<<"$window")"
    workspace="$(jq -r '.workspace.name // empty' <<<"$window")"
    floating="$(jq -r '.floating // false' <<<"$window")"
    read -r width height < <(scratch_size)

    [[ -n "$address" && "$address" != "0x0" ]] || exit 0
    [[ "$workspace" != special:* ]] || {
        lua_dispatch "hl.dsp.workspace.toggle_special(\"$scratch_name\")"
        exit 0
    }

    stack_push "$address|$workspace|$floating"
    lua_dispatch "hl.dsp.window.move({ workspace = \"special:$scratch_name\", follow = false, window = \"address:$address\" })"
    lua_dispatch "hl.dsp.window.float({ action = \"set\", window = \"address:$address\" })"
    lua_dispatch "hl.dsp.window.resize({ x = $width, y = $height, window = \"address:$address\" })"
    lua_dispatch "hl.dsp.window.center({ window = \"address:$address\" })"
}

pop_last() {
    local record address origin_workspace was_floating target_workspace
    record="$(stack_pop_existing)" || exit 0

    IFS='|' read -r address origin_workspace was_floating <<<"$record"
    target_workspace="$(current_workspace_name)"
    [[ "$target_workspace" != special:* ]] || target_workspace="$origin_workspace"

    lua_dispatch "hl.dsp.window.move({ workspace = \"name:$target_workspace\", follow = true, window = \"address:$address\" })"
    if [[ "$was_floating" == "false" ]]; then
        lua_dispatch "hl.dsp.window.float({ action = \"unset\", window = \"address:$address\" })"
    else
        lua_dispatch "hl.dsp.window.float({ action = \"set\", window = \"address:$address\" })"
        lua_dispatch "hl.dsp.window.center({ window = \"address:$address\" })"
    fi
    lua_dispatch "hl.dsp.focus({ window = \"address:$address\" })"
}

toggle_scratch() {
    lua_dispatch "hl.dsp.workspace.toggle_special(\"$scratch_name\")"
}

case "${1:-toggle}" in
    push)
        push_active
        ;;
    pop)
        pop_last
        ;;
    toggle)
        toggle_scratch
        ;;
    *)
        echo "usage: $0 {push|pop|toggle}" >&2
        exit 2
        ;;
esac
