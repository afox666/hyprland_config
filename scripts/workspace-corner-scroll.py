#!/usr/bin/env python3
import ctypes
import fcntl
import os
from pathlib import Path
import subprocess
import sys


APP_ID = "io.github.yaosong.HyprWorkspaceCornerScroll"
NAMESPACE = "hypr-workspace-corner-scroll"
HOTCORNER_SIZE = 96

EDGE_LEFT = 0
EDGE_BOTTOM = 3
LAYER_OVERLAY = 3
KEYBOARD_MODE_NONE = 0


def _hypr_dirs():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        yield Path(runtime_dir) / "hypr"
    yield Path("/tmp/hypr")


def _instance_from_dir(instance_dir):
    socket = instance_dir / ".socket.sock"
    if not socket.exists():
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
        mtime = max(socket.stat().st_mtime, lock.stat().st_mtime if lock.exists() else 0)
    except OSError:
        mtime = 0

    return {
        "signature": instance_dir.name,
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
    instance = find_hypr_instance()
    if instance:
        os.environ.setdefault("HYPRLAND_INSTANCE_SIGNATURE", instance["signature"])
        if instance["wayland_display"]:
            os.environ.setdefault("WAYLAND_DISPLAY", instance["wayland_display"])

    os.environ.setdefault("GDK_BACKEND", "wayland")


prepare_hypr_env()

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, Gtk  # noqa: E402


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


def hyprctl_dispatch_workspace(workspace):
    prepare_hypr_env()
    env = os.environ.copy()
    dispatcher = f'hl.dsp.focus({{ workspace = "{workspace}" }})'
    subprocess.run(
        ["hyprctl", "dispatch", dispatcher],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def on_scroll(_widget, event):
    direction = event.direction

    if direction == Gdk.ScrollDirection.SMOOTH:
        ok, _dx, dy = event.get_scroll_deltas()
        if ok:
            if dy > 0:
                direction = Gdk.ScrollDirection.DOWN
            elif dy < 0:
                direction = Gdk.ScrollDirection.UP

    if direction == Gdk.ScrollDirection.DOWN:
        hyprctl_dispatch_workspace("e+1")
        return True
    if direction == Gdk.ScrollDirection.UP:
        hyprctl_dispatch_workspace("e-1")
        return True
    return False


def install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(
        b"""
        .workspace-corner-scroll-window,
        .workspace-corner-scroll-hitbox {
            background: transparent;
        }
        """
    )
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def create_hotcorner(app, monitor):
    window = Gtk.ApplicationWindow(application=app)
    window.set_title(NAMESPACE)
    window.set_decorated(False)
    window.set_resizable(False)
    window.set_can_focus(False)
    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_skip_taskbar_hint(True)
    window.set_type_hint(Gdk.WindowTypeHint.DOCK)
    window.set_app_paintable(True)
    window.set_default_size(HOTCORNER_SIZE, HOTCORNER_SIZE)
    window.get_style_context().add_class("workspace-corner-scroll-window")

    screen = window.get_screen()
    visual = screen.get_rgba_visual() if screen else None
    if visual:
        window.set_visual(visual)

    window_ptr = gobject_ptr(window)
    LAYER_SHELL.gtk_layer_init_for_window(window_ptr)
    LAYER_SHELL.gtk_layer_set_namespace(window_ptr, NAMESPACE.encode())
    LAYER_SHELL.gtk_layer_set_layer(window_ptr, LAYER_OVERLAY)
    LAYER_SHELL.gtk_layer_set_anchor(window_ptr, EDGE_LEFT, 1)
    LAYER_SHELL.gtk_layer_set_anchor(window_ptr, EDGE_BOTTOM, 1)
    LAYER_SHELL.gtk_layer_set_exclusive_zone(window_ptr, 0)
    LAYER_SHELL.gtk_layer_set_keyboard_mode(window_ptr, KEYBOARD_MODE_NONE)
    if monitor is not None:
        LAYER_SHELL.gtk_layer_set_monitor(window_ptr, gobject_ptr(monitor))

    hitbox = Gtk.EventBox()
    hitbox.set_visible_window(False)
    hitbox.set_size_request(HOTCORNER_SIZE, HOTCORNER_SIZE)
    hitbox.set_can_focus(False)
    hitbox.get_style_context().add_class("workspace-corner-scroll-hitbox")
    hitbox.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    hitbox.connect("scroll-event", on_scroll)

    window.add(hitbox)
    window.show_all()
    return window


class HotcornerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.windows = []

    def do_activate(self):
        if not LAYER_SHELL.gtk_layer_is_supported():
            print("wlr layer shell is not supported by this compositor", file=sys.stderr)
            self.quit()
            return

        install_css()
        display = Gdk.Display.get_default()
        count = display.get_n_monitors() if display else 0

        if count == 0:
            self.windows.append(create_hotcorner(self, None))
            return

        for index in range(count):
            self.windows.append(create_hotcorner(self, display.get_monitor(index)))


if __name__ == "__main__":
    raise SystemExit(HotcornerApp().run(sys.argv))
