#!/usr/bin/env python3
import ctypes
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading


APP_ID = "io.github.yaosong.HyprScratchpadStatus"
NAMESPACE = "hypr-scratchpad-status"
SCRATCH_NAME = "scratch"
SCRATCH_WORKSPACE = f"special:{SCRATCH_NAME}"
SCRATCHPAD_SCRIPT = str(Path.home() / ".config/hypr/scripts/hypr-scratchpad.sh")

EDGE_TOP = 2
LAYER_OVERLAY = 3
KEYBOARD_MODE_NONE = 0


def _hypr_dirs():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        yield Path(runtime_dir) / "hypr"
    yield Path(f"/run/user/{os.getuid()}") / "hypr"
    yield Path("/tmp/hypr")


def _instance_from_dir(instance_dir):
    event_socket = instance_dir / ".socket2.sock"
    socket_path = instance_dir / ".socket.sock"
    if not socket_path.exists():
        return None

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

    for base in _hypr_dirs():
        if not base.exists():
            continue
        if signature:
            current = _instance_from_dir(base / signature)
            if current:
                return current

    candidates = []
    for base in _hypr_dirs():
        if not base.exists():
            continue
        for instance_dir in base.iterdir():
            if not instance_dir.is_dir():
                continue
            instance = _instance_from_dir(instance_dir)
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
        os.environ.setdefault("HYPRLAND_INSTANCE_SIGNATURE", instance["signature"])
        if instance["wayland_display"]:
            os.environ.setdefault("WAYLAND_DISPLAY", instance["wayland_display"])

    os.environ.setdefault("GDK_BACKEND", "wayland")
    return instance


INSTANCE = prepare_hypr_env()

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402


def gobject_ptr(obj):
    return ctypes.c_void_p(hash(obj))


def load_layer_shell():
    for name in (
        "/usr/lib/x86_64-linux-gnu/libgtk-layer-shell.so.0",
        "libgtk-layer-shell.so.0",
    ):
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            lib = None

    if lib is None:
        print("gtk-layer-shell library not found", file=sys.stderr)
        sys.exit(1)

    lib.gtk_layer_is_supported.restype = ctypes.c_int
    lib.gtk_layer_init_for_window.argtypes = [ctypes.c_void_p]
    lib.gtk_layer_set_namespace.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.gtk_layer_set_layer.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.gtk_layer_set_monitor.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gtk_layer_set_anchor.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.gtk_layer_set_exclusive_zone.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.gtk_layer_set_keyboard_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.gtk_layer_set_margin.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    return lib


LAYER_SHELL = load_layer_shell()


def acquire_lock():
    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/{os.getuid()}"))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock = open(runtime_dir / f"{NAMESPACE}.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)
    return lock


LOCK_FILE = acquire_lock()


def hyprctl_json(*args):
    prepare_hypr_env()
    result = subprocess.run(
        ["hyprctl", *args, "-j"],
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def run_scratchpad_action(action):
    prepare_hypr_env()
    subprocess.Popen(
        [SCRATCHPAD_SCRIPT, action],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def scratchpad_state():
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

    focused = None
    active = hyprctl_json("activewindow")
    if active and active.get("workspace", {}).get("name") == SCRATCH_WORKSPACE:
        focused = active

    current = focused or (scratch_clients[-1] if scratch_clients else None)
    title = ""
    if current:
        title = current.get("title") or current.get("class") or ""

    return {
        "count": len(scratch_clients),
        "visible": visible,
        "title": title,
    }


def install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(
        b"""
        .scratch-status-window {
            background: transparent;
        }

        .scratch-status-box {
            background: rgba(20, 24, 28, 0.88);
            border: 1px solid rgba(92, 214, 176, 0.72);
            border-radius: 8px;
            color: #f3f7f5;
            padding: 5px 12px;
        }

        .scratch-status-hidden {
            border-color: rgba(180, 188, 196, 0.62);
            color: #d7dde1;
        }

        .scratch-status-count {
            color: #58d68d;
            font-weight: 700;
        }

        .scratch-status-title {
            color: #f3f7f5;
        }

        .scratch-status-hidden .scratch-status-title {
            color: #c8d0d5;
        }
        """
    )
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class StatusWindow:
    def __init__(self, app, monitor):
        self.window = Gtk.ApplicationWindow(application=app)
        self.window.set_title(NAMESPACE)
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_can_focus(False)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.window.set_app_paintable(True)
        self.window.set_default_size(620, 34)
        self.window.get_style_context().add_class("scratch-status-window")

        screen = self.window.get_screen()
        visual = screen.get_rgba_visual() if screen else None
        if visual:
            self.window.set_visual(visual)

        window_ptr = gobject_ptr(self.window)
        LAYER_SHELL.gtk_layer_init_for_window(window_ptr)
        LAYER_SHELL.gtk_layer_set_namespace(window_ptr, NAMESPACE.encode())
        LAYER_SHELL.gtk_layer_set_layer(window_ptr, LAYER_OVERLAY)
        LAYER_SHELL.gtk_layer_set_anchor(window_ptr, EDGE_TOP, 1)
        LAYER_SHELL.gtk_layer_set_margin(window_ptr, EDGE_TOP, 8)
        LAYER_SHELL.gtk_layer_set_exclusive_zone(window_ptr, 0)
        LAYER_SHELL.gtk_layer_set_keyboard_mode(window_ptr, KEYBOARD_MODE_NONE)
        if monitor is not None:
            LAYER_SHELL.gtk_layer_set_monitor(window_ptr, gobject_ptr(monitor))

        event_box = Gtk.EventBox()
        event_box.set_visible_window(False)
        event_box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        event_box.connect("button-press-event", self.on_click)

        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.box.set_halign(Gtk.Align.CENTER)
        self.box.set_valign(Gtk.Align.CENTER)
        self.box.get_style_context().add_class("scratch-status-box")

        self.count_label = Gtk.Label()
        self.count_label.get_style_context().add_class("scratch-status-count")

        self.title_label = Gtk.Label()
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_max_width_chars(52)
        self.title_label.get_style_context().add_class("scratch-status-title")

        self.box.pack_start(self.count_label, False, False, 0)
        self.box.pack_start(self.title_label, True, True, 0)
        event_box.add(self.box)
        self.window.add(event_box)
        self.window.hide()

    def on_click(self, _widget, event):
        if event.button == 1:
            run_scratchpad_action("toggle")
            return True
        if event.button == 3:
            run_scratchpad_action("pop")
            return True
        return False

    def update(self, state):
        count = state["count"]
        if count <= 0:
            self.window.hide()
            return

        style = self.box.get_style_context()
        if state["visible"]:
            style.remove_class("scratch-status-hidden")
            status = "抽屉 开"
        else:
            style.add_class("scratch-status-hidden")
            status = "抽屉 收"

        self.count_label.set_text(f"{status} {count}")
        title = state["title"] or "空标题窗口"
        self.title_label.set_text(title)
        self.window.show_all()


class ScratchStatusApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.windows = []
        self.update_scheduled = False

    def do_activate(self):
        if not LAYER_SHELL.gtk_layer_is_supported():
            print("wlr layer shell is not supported by this compositor", file=sys.stderr)
            self.quit()
            return

        install_css()
        display = Gdk.Display.get_default()
        count = display.get_n_monitors() if display else 0

        if count == 0:
            self.windows.append(StatusWindow(self, None))
        else:
            for index in range(count):
                self.windows.append(StatusWindow(self, display.get_monitor(index)))

        self.refresh()
        GLib.timeout_add_seconds(2, self.refresh)
        threading.Thread(target=self.watch_hypr_events, daemon=True).start()

    def schedule_refresh(self):
        if self.update_scheduled:
            return
        self.update_scheduled = True
        GLib.timeout_add(80, self._scheduled_refresh)

    def _scheduled_refresh(self):
        self.update_scheduled = False
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        state = scratchpad_state()
        for window in self.windows:
            window.update(state)
        return GLib.SOURCE_CONTINUE

    def watch_hypr_events(self):
        global INSTANCE
        while True:
            INSTANCE = prepare_hypr_env()
            event_socket = INSTANCE["event_socket"] if INSTANCE else None
            if not event_socket or not event_socket.exists():
                GLib.idle_add(self.schedule_refresh)
                threading.Event().wait(2)
                continue

            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.connect(str(event_socket))
                    with sock.makefile("r", encoding="utf-8", errors="ignore") as stream:
                        for _line in stream:
                            GLib.idle_add(self.schedule_refresh)
            except OSError:
                GLib.idle_add(self.schedule_refresh)
                threading.Event().wait(1)


if __name__ == "__main__":
    raise SystemExit(ScratchStatusApp().run(sys.argv))
