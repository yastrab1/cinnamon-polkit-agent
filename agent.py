#!/usr/bin/python3
"""Standalone polkit authentication agent that looks like Cinnamon's built-in one.

Flow mirrors /usr/share/cinnamon/js/ui/polkitAuthenticationAgent.js; drawing is in render.py.
"""
import os
import pwd
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Polkit", "1.0")
gi.require_version("PolkitAgent", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Polkit, PolkitAgent  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402

LIGHTBOX_ALPHA = 0.4
CARET_BLINK_MS = 600
SORRY = "Sorry, that didn't work. Please try again."


def display_name(username):
    try:
        gecos = pwd.getpwnam(username).pw_gecos.split(",")[0].strip()
    except KeyError:
        gecos = ""
    return gecos or username


def init_layer_shell(window):
    """Put the window on the wlr-layer-shell overlay layer with exclusive keyboard
    focus (like a lock screen), so it gets typed input without a click.

    Uses libgtk-layer-shell through ctypes, so its GI typelib isn't needed.
    Returns False when unavailable (X11, or a compositor without layer-shell)."""
    import ctypes
    try:
        lib = ctypes.CDLL("libgtk-layer-shell.so.0")
    except OSError:
        return False
    if not lib.gtk_layer_is_supported():
        return False
    get_ptr = ctypes.pythonapi.PyCapsule_GetPointer
    get_ptr.restype = ctypes.c_void_p
    get_ptr.argtypes = [ctypes.py_object, ctypes.c_char_p]
    win = ctypes.c_void_p(get_ptr(window.__gpointer__, None))
    lib.gtk_layer_init_for_window(win)
    lib.gtk_layer_set_namespace(win, b"polkit-agent")
    lib.gtk_layer_set_layer(win, 3)  # GTK_LAYER_SHELL_LAYER_OVERLAY
    for edge in range(4):  # LEFT, RIGHT, TOP, BOTTOM
        lib.gtk_layer_set_anchor(win, edge, 1)
    lib.gtk_layer_set_exclusive_zone(win, -1)
    lib.gtk_layer_set_keyboard_mode(win, 1)  # GTK_LAYER_SHELL_KEYBOARD_MODE_EXCLUSIVE
    return True


class AuthDialog(Gtk.Window):
    def __init__(self, message, cookie, identities, on_done):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.cookie = cookie
        self.on_done = on_done
        self.session = None
        self.completed = False
        self.done = False

        names = [n for n in (u.get_name() for u in identities) if n]
        me = GLib.get_user_name()
        self.username = me if me in names else (names[0] if names else "root")
        self.identity = Polkit.UnixUser.new_for_name(self.username)

        self.s = dict(
            title="Authentication Required", description=message,
            user=display_name(self.username), hint="Password",
            password="", password_len=0, peek=False, caret=True,
            focus="entry", hover=None, active=None, ok_sensitive=False,
            message=None, message_error=False, entry_sensitive=True,
        )
        self.entry_visible = False
        self.dialog_xy = (0, 0)

        self.set_title("Authentication Required")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("key-press-event", self.on_key)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-press-event", self.on_press)
        self.connect("button-release-event", self.on_release)
        self.connect("delete-event", lambda *a: (self.cancel(), True)[1])
        self.blink_id = GLib.timeout_add(CARET_BLINK_MS, self.blink)
        if not init_layer_shell(self):
            self.fullscreen()

    # ---- drawing / input -------------------------------------------------
    def on_draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cr.set_operator(1)  # SOURCE
        cr.set_source_rgba(0, 0, 0, LIGHTBOX_ALPHA)
        cr.paint()
        cr.set_operator(2)  # OVER
        x, y = (w - render.W) // 2, (h - render.H) // 2
        self.dialog_xy = (x, y)
        cr.translate(x, y)
        state = dict(self.s)
        if not self.entry_visible:
            state["focus"] = "cancel" if state["focus"] == "entry" else state["focus"]
        render.draw_dialog(cr, state)
        return True

    def blink(self):
        self.s["caret"] = not self.s["caret"]
        self.queue_draw()
        return True

    def local(self, ev):
        return ev.x - self.dialog_xy[0], ev.y - self.dialog_xy[1]

    def on_motion(self, _w, ev):
        hit = render.hit(*self.local(ev))
        hover = "entry" if hit == "eye" else hit
        if hover == "auth" and not self.s["ok_sensitive"]:
            hover = None
        if hover != self.s["hover"]:
            self.s["hover"] = hover
            self.queue_draw()

    def on_press(self, _w, ev):
        hit = render.hit(*self.local(ev))
        if hit in ("cancel", "auth") and (hit != "auth" or self.s["ok_sensitive"]):
            self.s["active"] = hit
        elif hit in ("entry", "eye") and self.entry_visible:
            self.s["focus"] = "entry"
            if hit == "eye":
                self.s["peek"] = not self.s["peek"]
        self.queue_draw()

    def on_release(self, _w, ev):
        hit = render.hit(*self.local(ev))
        pressed, self.s["active"] = self.s["active"], None
        if pressed and pressed == hit:
            if hit == "cancel":
                self.cancel()
            elif hit == "auth":
                self.submit()
        self.queue_draw()

    def on_key(self, _w, ev):
        key = ev.keyval
        if key == Gdk.KEY_Escape:
            self.cancel()
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self.s["focus"] == "cancel":
                self.cancel()
            else:
                self.submit()
        elif key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            order = ["entry", "cancel", "auth"] if self.entry_visible else ["cancel", "auth"]
            if not self.s["ok_sensitive"]:
                order.remove("auth")
            cur = self.s["focus"] if self.s["focus"] in order else order[0]
            step = -1 if key == Gdk.KEY_ISO_Left_Tab else 1
            self.s["focus"] = order[(order.index(cur) + step) % len(order)]
        elif self.s["focus"] == "entry" and self.s["entry_sensitive"]:
            if key == Gdk.KEY_BackSpace:
                self.set_password(self.s["password"][:-1])
            elif ev.state & Gdk.ModifierType.CONTROL_MASK and key in (Gdk.KEY_u, Gdk.KEY_U):
                self.set_password("")
            else:
                ch = Gdk.keyval_to_unicode(key)
                if ch and ch >= 32 and not ev.state & Gdk.ModifierType.CONTROL_MASK:
                    self.set_password(self.s["password"] + chr(ch))
        self.s["caret"] = True
        self.queue_draw()
        return True

    def set_password(self, pw):
        self.s["password"] = pw
        self.s["password_len"] = len(pw)
        self.s["ok_sensitive"] = len(pw) > 0

    # ---- polkit session (same flow as Cinnamon) -------------------------
    def start(self):
        self.destroy_session()
        self.session = PolkitAgent.Session.new(self.identity, self.cookie)
        self.session.connect("completed", self.on_completed)
        self.session.connect("request", self.on_request)
        self.session.connect("show-error", self.on_show_error)
        self.session.connect("show-info", self.on_show_info)
        self.session.initiate()

    def destroy_session(self):
        if self.session is not None:
            if not self.completed:
                self.session.cancel()
            self.session = None
        self.completed = False

    def on_request(self, _session, request, echo_on):
        self.s["hint"] = "Password" if request.strip() in ("Password:", "") else request
        self.s["peek"] = bool(echo_on)
        self.set_password("")
        self.s["entry_sensitive"] = True
        self.s["focus"] = "entry"
        self.entry_visible = True
        self.show_all()
        self.present()
        self.queue_draw()

    def on_show_error(self, _session, text):
        self.set_password("")
        self.s.update(message=text, message_error=True)
        self.show_all()
        self.queue_draw()

    def on_show_info(self, _session, text):
        self.set_password("")
        self.s.update(message=text, message_error=False)
        self.show_all()
        self.queue_draw()

    def on_completed(self, _session, gained):
        if self.completed or self.done:
            return
        self.completed = True
        if gained:
            self.finish(False)
            return
        if not (self.s["message"] and self.s["message_error"]):
            self.s.update(message=SORRY, message_error=True)
        self.start()

    def submit(self):
        pw = self.s["password"]
        if not pw or self.session is None or not self.s["entry_sensitive"]:
            return
        self.s["entry_sensitive"] = False
        self.s["ok_sensitive"] = False
        self.s["message"] = None
        self.session.response(pw)
        self.queue_draw()

    def cancel(self):
        self.finish(True)

    def finish(self, dismissed):
        if self.done:
            return
        self.done = True
        GLib.source_remove(self.blink_id)
        self.destroy_session()
        self.destroy()
        self.on_done(dismissed)


AGENT_PATH = "/org/cinnamon/PolkitAgentReplica"
AGENT_XML = """
<node>
  <interface name="org.freedesktop.PolicyKit1.AuthenticationAgent">
    <method name="BeginAuthentication">
      <arg type="s" name="action_id" direction="in"/>
      <arg type="s" name="message" direction="in"/>
      <arg type="s" name="icon_name" direction="in"/>
      <arg type="a{ss}" name="details" direction="in"/>
      <arg type="s" name="cookie" direction="in"/>
      <arg type="a(sa{sv})" name="identities" direction="in"/>
    </method>
    <method name="CancelAuthentication">
      <arg type="s" name="cookie" direction="in"/>
    </method>
  </interface>
</node>
"""


def identities_to_users(identities):
    """polkit identities -> Polkit.UnixUser list (groups expanded to their members)."""
    import grp
    users = []
    for kind, props in identities:
        try:
            if kind == "unix-user":
                users.append(Polkit.UnixUser.new(int(props["uid"])))
            elif kind == "unix-group":
                gid = int(props["gid"])
                members = set(grp.getgrgid(gid).gr_mem)
                members |= {p.pw_name for p in pwd.getpwall() if p.pw_gid == gid}
                users += [Polkit.UnixUser.new_for_name(m) for m in sorted(members)]
        except (KeyError, ValueError, GLib.Error):
            continue
    return [u for u in users if u is not None]


class Agent:
    """Implements polkit's AuthenticationAgent D-Bus interface directly."""

    def __init__(self, system_bus):
        self.bus = system_bus
        self.dialog = None
        self.current = None  # (cookie, invocation)
        self.queue = []
        node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
        self.bus.register_object(AGENT_PATH, node.interfaces[0], self.on_call, None, None)

    def on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "BeginAuthentication":
            _action, message, _icon, _details, cookie, identities = params.unpack()
            self.queue.append((message, cookie, identities_to_users(identities), invocation))
            if self.dialog is None:
                self.next()
        elif method == "CancelAuthentication":
            (cookie,) = params.unpack()
            if self.current and self.current[0] == cookie and self.dialog:
                self.dialog.finish(True)
            else:
                for item in list(self.queue):
                    if item[1] == cookie:
                        self.queue.remove(item)
                        self.reply(item[3], True)
            invocation.return_value(None)

    @staticmethod
    def reply(invocation, dismissed):
        if dismissed:
            invocation.return_dbus_error("org.freedesktop.PolicyKit1.Error.Cancelled",
                                         "Authentication dialog was dismissed by the user")
        else:
            invocation.return_value(None)

    def next(self):
        if not self.queue:
            self.dialog = self.current = None
            return False
        message, cookie, users, invocation = self.queue.pop(0)
        self.current = (cookie, invocation)

        def done(dismissed):
            self.dialog = self.current = None
            self.reply(invocation, dismissed)
            GLib.idle_add(self.next)

        self.dialog = AuthDialog(message, cookie, users, done)
        self.dialog.start()
        return False


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    session = Polkit.UnixSession.new_for_process_sync(os.getpid(), None)
    sid = session.get_session_id() if session else os.environ.get("XDG_SESSION_ID")
    if not sid:
        sys.exit("cinnamon-polkit-agent: cannot determine login session")
    agent = Agent(bus)  # noqa: F841 (keeps the exported object alive)
    subject = ("unix-session", {"session-id": GLib.Variant("s", sid)})
    locale = os.environ.get("LANG", "en_US.UTF-8")
    try:
        bus.call_sync("org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority",
                      "org.freedesktop.PolicyKit1.Authority", "RegisterAuthenticationAgent",
                      GLib.Variant("((sa{sv})ss)", (subject, locale, AGENT_PATH)),
                      None, Gio.DBusCallFlags.NONE, -1, None)
    except GLib.Error as e:
        sys.exit(f"cinnamon-polkit-agent: failed to register: {e.message}")
    Gtk.main()


if __name__ == "__main__":
    main()
