#!/usr/bin/env python3
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time


SCRATCH_NAME = "scratch"
SCRATCH_WORKSPACE = f"special:{SCRATCH_NAME}"
POLL_SECONDS = 5


def hypr_dirs():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        yield Path(runtime_dir) / "hypr"
    yield Path(f"/run/user/{os.getuid()}") / "hypr"
    yield Path("/tmp/hypr")


def instance_from_dir(instance_dir):
    socket_path = instance_dir / ".socket.sock"
    if not socket_path.exists():
        return None

    event_socket = instance_dir / ".socket2.sock"
    lock = instance_dir / "hyprland.lock"
    pid = None
    wayland_display = None
    live = False

    if lock.exists():
        lines = lock.read_text(errors="ignore").splitlines()
        if lines:
            try:
                pid = int(lines[0])
                live = Path(f"/proc/{pid}").exists()
            except ValueError:
                pass
        if len(lines) > 1 and lines[1]:
            wayland_display = lines[1]

    try:
        mtime = max(socket_path.stat().st_mtime, lock.stat().st_mtime if lock.exists() else 0)
    except OSError:
        mtime = 0

    return {
        "signature": instance_dir.name,
        "event_socket": event_socket,
        "wayland_display": wayland_display,
        "live": live,
        "mtime": mtime,
    }


def find_hypr_instance():
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")

    if signature:
        for base in hypr_dirs():
            if not base.exists():
                continue
            current = instance_from_dir(base / signature)
            if current:
                return current

    candidates = []
    for base in hypr_dirs():
        if not base.exists():
            continue
        for instance_dir in base.iterdir():
            if not instance_dir.is_dir():
                continue
            instance = instance_from_dir(instance_dir)
            if instance:
                candidates.append(instance)

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item["live"], item["mtime"]))
    return candidates[-1]


def prepare_hypr_env():
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    instance = find_hypr_instance()
    if instance:
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = instance["signature"]
        if instance["wayland_display"]:
            os.environ.setdefault("WAYLAND_DISPLAY", instance["wayland_display"])
    return instance


def hyprctl_json(*args):
    prepare_hypr_env()
    try:
        result = subprocess.run(
            ["hyprctl", *args, "-j"],
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def scratchpad_payload():
    clients = hyprctl_json("clients") or []
    monitors = hyprctl_json("monitors") or []
    scratch_clients = [
        client for client in clients
        if client.get("workspace", {}).get("name") == SCRATCH_WORKSPACE
    ]
    visible = any(
        monitor.get("specialWorkspace", {}).get("name") == SCRATCH_WORKSPACE
        for monitor in monitors
    )

    current = None
    active = hyprctl_json("activewindow")
    if active and active.get("workspace", {}).get("name") == SCRATCH_WORKSPACE:
        current = active
    elif scratch_clients:
        current = scratch_clients[-1]

    count = len(scratch_clients)
    title = ""
    if current:
        title = current.get("title") or current.get("class") or ""

    if count == 0:
        text = "抽屉 0"
        css_class = "empty"
        alt = "empty"
        status = "空"
    elif visible:
        text = f"抽屉 开 {count}"
        css_class = "open"
        alt = "open"
        status = "打开"
    else:
        text = f"抽屉 收 {count}"
        css_class = "closed"
        alt = "closed"
        status = "收起"

    tooltip = [
        f"抽屉: {status}",
        f"窗口: {count}",
        "左键: 打开/收起",
        "右键: 收纳当前窗口",
        "中键: 弹出最近窗口",
    ]
    if title:
        tooltip.append(f"当前: {title}")

    return {
        "text": text,
        "alt": alt,
        "class": css_class,
        "tooltip": "\n".join(tooltip),
    }


def emit(previous=None, force=False):
    encoded = json.dumps(scratchpad_payload(), ensure_ascii=False)
    if force or encoded != previous:
        print(encoded, flush=True)
        return encoded
    return previous


def stream_status():
    previous = None

    while True:
        instance = prepare_hypr_env()
        previous = emit(previous, force=previous is None)
        event_socket = instance["event_socket"] if instance else None

        if not event_socket or not event_socket.exists():
            time.sleep(POLL_SECONDS)
            previous = emit(previous)
            continue

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(str(event_socket))
                sock.setblocking(False)
                buffer = b""

                while True:
                    readable, _, _ = select.select([sock], [], [], POLL_SECONDS)
                    if not readable:
                        previous = emit(previous)
                        continue

                    chunk = sock.recv(4096)
                    if not chunk:
                        break

                    buffer += chunk
                    while b"\n" in buffer:
                        _, buffer = buffer.split(b"\n", 1)
                        previous = emit(previous)
        except OSError:
            time.sleep(1)


def main():
    if "--once" in sys.argv:
        emit(force=True)
        return 0

    stream_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
