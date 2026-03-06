"""Voice-driven button click mode.

Uses macOS Accessibility APIs to discover all clickable UI elements in the
frontmost application's focused window, overlays numbered badges on each,
and clicks the corresponding element when the user speaks its number.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSScreen,
    NSTextAlignmentCenter,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from ApplicationServices import (
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXValueGetValue,
    kAXErrorSuccess,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from Foundation import NSObject
from Quartz import CGEventCreate, CGEventGetLocation

from schnoz_app.platform import CursorController


# -- Main-thread dispatch helper -------------------------------------------

class _ChunksTrampoline(NSObject):
    """Dispatch callables to the main AppKit thread via performSelector."""
    _callables: list = []

    def fire_(self, _sender):
        while self._callables:
            fn = self._callables.pop(0)
            fn()


_trampoline = _ChunksTrampoline.alloc().init()


def _dispatch_to_main(fn):
    """Schedule a no-arg callable to run on the main thread."""
    _trampoline._callables.append(fn)
    _trampoline.performSelectorOnMainThread_withObject_waitUntilDone_(
        "fire:", None, False,
    )

# -- Accessibility discovery constants ------------------------------------

_CLICKABLE_ROLES = frozenset({
    "AXButton",
    "AXCheckBox",
    "AXRadioButton",
    "AXLink",
    "AXPopUpButton",
    "AXMenuButton",
    "AXTab",
    "AXDisclosureTriangle",
    "AXComboBox",
    "AXToolbarButton",
    "AXIncrementor",
    "AXMenuItem",
    "AXSlider",
    "AXColorWell",
    "AXSwitch",
    "AXSegmentedControl",
    "AXDockItem",       # Dock app icons
    "AXMenuBarItem",    # Menu bar items (Control Center, Wi-Fi, etc.)
})

# Actions that indicate an element is clickable
_CLICK_ACTIONS = frozenset({
    "AXPress",
    "AXOpen",
    "AXPick",
    "AXConfirm",
})

_MAX_TRAVERSAL = 10000  # max AX nodes to visit
_MAX_ELEMENTS = 999    # max clickable elements to label
_MIN_SIZE = 8.0        # minimum width/height in pixels

# -- Badge overlay constants -----------------------------------------------

_BADGE_W = 34.0
_BADGE_H = 20.0
_BADGE_FONT_SIZE = 12.0
_POST_CLICK_DELAY = 0.5


# -- Data model ------------------------------------------------------------

@dataclass
class _ClickableElement:
    role: str
    label: str
    x: float       # screen x (top-left origin, same as CGEvent / AX)
    y: float       # screen y (top-left origin)
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0


# -- Accessibility tree traversal ------------------------------------------

def _get_target_window(ax_app):
    """Get the focused window, falling back to main window, then first window."""
    for attr in ("AXFocusedWindow", "AXMainWindow"):
        err, win = AXUIElementCopyAttributeValue(ax_app, attr, None)
        if err == kAXErrorSuccess and win is not None:
            return win
    err, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
    if err == kAXErrorSuccess and windows and len(windows) > 0:
        return windows[0]
    return None


def _extract_element_info(elem, role: str) -> _ClickableElement | None:
    """Extract position/size from an AX element, return None if unavailable."""
    err_p, pos_val = AXUIElementCopyAttributeValue(elem, "AXPosition", None)
    err_s, size_val = AXUIElementCopyAttributeValue(elem, "AXSize", None)
    if err_p != kAXErrorSuccess or err_s != kAXErrorSuccess:
        return None
    if pos_val is None or size_val is None:
        return None

    _, point = AXValueGetValue(pos_val, kAXValueCGPointType, None)
    _, size = AXValueGetValue(size_val, kAXValueCGSizeType, None)
    if point is None or size is None:
        return None

    # Try to get a human-readable label for debugging
    label = ""
    for attr in ("AXTitle", "AXDescription", "AXHelp"):
        err, val = AXUIElementCopyAttributeValue(elem, attr, None)
        if err == kAXErrorSuccess and val:
            label = str(val)
            break

    return _ClickableElement(
        role=role,
        label=label,
        x=float(point.x),
        y=float(point.y),
        width=float(size.width),
        height=float(size.height),
    )


def _is_on_screen(elem: _ClickableElement, screen_w: float, screen_h: float) -> bool:
    """Check element is visible and meets minimum size."""
    if elem.width < _MIN_SIZE or elem.height < _MIN_SIZE:
        return False
    # Element must be at least partially on screen
    if elem.x + elem.width < 0 or elem.x > screen_w:
        return False
    if elem.y + elem.height < 0 or elem.y > screen_h:
        return False
    return True


def _deduplicate(elements: list[_ClickableElement], tolerance: float = 5.0) -> list[_ClickableElement]:
    """Remove elements that overlap at the same center position."""
    seen: list[tuple[float, float]] = []
    result: list[_ClickableElement] = []
    for e in elements:
        cx, cy = e.center_x, e.center_y
        is_dup = False
        for sx, sy in seen:
            if abs(cx - sx) < tolerance and abs(cy - sy) < tolerance:
                is_dup = True
                break
        if not is_dup:
            result.append(e)
            seen.append((cx, cy))
    return result


def _bfs_app(roots: list, screen_w: float, screen_h: float, budget: int) -> tuple[list[_ClickableElement], int]:
    """BFS one app's windows/menu bar. Returns (elements, nodes_visited)."""
    elements: list[_ClickableElement] = []
    visited = 0
    q: deque = deque(roots)

    while q and visited < budget:
        elem = q.popleft()
        visited += 1

        err, role = AXUIElementCopyAttributeValue(elem, "AXRole", None)
        if err != kAXErrorSuccess or role is None:
            err_c, children = AXUIElementCopyAttributeValue(elem, "AXChildren", None)
            if err_c == kAXErrorSuccess and children:
                q.extend(children)
            continue

        is_clickable = role in _CLICKABLE_ROLES
        if not is_clickable:
            err_a, actions = AXUIElementCopyAttributeValue(elem, "AXActionNames", None)
            if err_a == kAXErrorSuccess and actions:
                is_clickable = bool(_CLICK_ACTIONS & set(actions))
        if is_clickable:
            ce = _extract_element_info(elem, role)
            if ce is not None and _is_on_screen(ce, screen_w, screen_h):
                elements.append(ce)

        err_c, children = AXUIElementCopyAttributeValue(elem, "AXChildren", None)
        if err_c == kAXErrorSuccess and children:
            q.extend(children)

    return elements, visited


def _discover_clickable_elements() -> list[_ClickableElement]:
    """Find all clickable UI elements across all visible apps on screen."""
    try:
        t0 = time.monotonic()
        main = NSScreen.mainScreen()
        if main is None:
            return []
        f = main.frame()
        screen_w = float(f.size.width)
        screen_h = float(f.size.height)

        workspace = NSWorkspace.sharedWorkspace()
        running_apps = workspace.runningApplications()
        frontmost = workspace.frontmostApplication()
        frontmost_pid = frontmost.processIdentifier() if frontmost else -1
        own_pid = NSWorkspace.sharedWorkspace().frontmostApplication()  # not reliable
        # Get our own pid to skip ourselves
        import os
        my_pid = os.getpid()

        all_elements: list[_ClickableElement] = []
        total_visited = 0
        app_count = 0

        for app in running_apps:
            # Abort if taking too long (3 second max)
            if time.monotonic() - t0 > 10.0:
                print(f"[chunks] Discovery timeout after {app_count} apps")
                break

            try:
                policy = app.activationPolicy()
                # 0 = regular, 1 = accessory (menu bar), 2 = background-only
                if policy == 2:
                    continue
                pid = app.processIdentifier()
                if pid <= 0 or pid == my_pid:
                    continue

                app_name = app.localizedName() or f"pid={pid}"
                ax_app = AXUIElementCreateApplication(pid)
                roots = []

                # Collect windows
                err, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
                if err == kAXErrorSuccess and windows:
                    try:
                        roots.extend(windows)
                    except TypeError:
                        roots.append(windows)

                # Menu bar — scan for every app (extras like Wi-Fi, battery
                # are owned by different processes)
                for bar_attr in ("AXMenuBar", "AXExtrasMenuBar"):
                    err, bar = AXUIElementCopyAttributeValue(ax_app, bar_attr, None)
                    if err == kAXErrorSuccess and bar is not None:
                        roots.append(bar)

                # Also try direct children (e.g. Dock exposes icons this way)
                err, children = AXUIElementCopyAttributeValue(ax_app, "AXChildren", None)
                if err == kAXErrorSuccess and children:
                    try:
                        roots.extend(children)
                    except TypeError:
                        roots.append(children)

                if not roots:
                    continue

                # Give frontmost app more budget, others less
                budget = _MAX_TRAVERSAL if pid == frontmost_pid else 5000
                elements, visited = _bfs_app(roots, screen_w, screen_h, budget)
                if elements:
                    print(f"[chunks]   {app_name}: {len(elements)} elements ({visited} nodes)")
                all_elements.extend(elements)
                total_visited += visited
                app_count += 1
            except Exception as e:
                print(f"[chunks]   Skipping app: {e}")
                continue

        all_elements = _deduplicate(all_elements)
        all_elements.sort(key=lambda e: (e.y, e.x))
        all_elements = all_elements[:_MAX_ELEMENTS]

        elapsed = time.monotonic() - t0
        print(f"[chunks] Discovered {len(all_elements)} clickable elements "
              f"(visited {total_visited} nodes across {app_count} apps in {elapsed:.1f}s)")
        return all_elements
    except Exception as e:
        print(f"[chunks] ERROR in discovery: {e}")
        import traceback
        traceback.print_exc()
        return []


# -- Overlay controller ----------------------------------------------------

class _ButtonOverlayController:
    """Manages transparent overlay windows with numbered badges on elements."""

    def __init__(self):
        self._window = None

    def showWithElements_(self, elements: list[_ClickableElement]):
        print(f"[chunks] showWithElements_ called with {len(elements)} elements")
        try:
            self.hide()
        except Exception as e:
            print(f"[chunks] hide() error: {e}")

        screen = NSScreen.mainScreen()
        if screen is None:
            print("[chunks] No display detected")
            return

        frame = screen.frame()
        screen_h = float(frame.size.height)

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setIgnoresMouseEvents_(True)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setLevel_(1000)  # above most windows including menu bar

        local_frame = ((0.0, 0.0), (frame.size.width, frame.size.height))
        content_view = NSView.alloc().initWithFrame_(local_frame)
        window.setContentView_(content_view)

        for idx, elem in enumerate(elements, start=1):
            # Position badge at top-left corner of the element
            badge_ax_x = elem.x
            badge_ax_y = elem.y

            # Clamp to screen bounds
            badge_ax_x = max(0.0, min(badge_ax_x, frame.size.width - _BADGE_W))
            badge_ax_y = max(0.0, min(badge_ax_y, screen_h - _BADGE_H))

            # Convert AX coords (top-left origin) to NSView coords (bottom-left origin)
            badge_nsview_x = badge_ax_x - float(frame.origin.x)
            badge_nsview_y = screen_h - badge_ax_y - _BADGE_H

            label = NSTextField.alloc().initWithFrame_(
                ((badge_nsview_x, badge_nsview_y), (_BADGE_W, _BADGE_H))
            )
            label.setStringValue_(str(idx))
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setBezeled_(False)
            label.setDrawsBackground_(True)
            label.setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.15, 0.1, 0.9)
            )
            label.setAlignment_(NSTextAlignmentCenter)
            label.setTextColor_(NSColor.whiteColor())
            label.setFont_(NSFont.boldSystemFontOfSize_(_BADGE_FONT_SIZE))
            label.setWantsLayer_(True)
            label.layer().setCornerRadius_(4.0)
            label.layer().setMasksToBounds_(True)
            content_view.addSubview_(label)

        window.orderFrontRegardless()
        self._window = window

        if not elements:
            print("[chunks] Overlay shown (no clickable elements found)")
        else:
            print(f"[chunks] Overlay shown with {len(elements)} badges")

    def hide(self):
        if self._window is not None:
            self._window.orderOut_(None)
            self._window = None
            print("[chunks] Overlay hidden")


# -- Main ChunksMode class -------------------------------------------------

class ChunksMode:
    """Accessibility-driven button overlay + voice-number click."""

    def __init__(self):
        self._cursor = CursorController()
        self._queue: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._overlay = _ButtonOverlayController()
        self._elements: list[_ClickableElement] = []

    def start(self, text_queue: queue.Queue):
        if self.running:
            return

        if not AXIsProcessTrusted():
            print("[chunks] WARNING: Accessibility not enabled. "
                  "Go to System Settings > Privacy & Security > Accessibility "
                  "and enable this app.")

        self._queue = text_queue
        self._stop.clear()

        self._thread = threading.Thread(target=self._loop, daemon=True, name="chunks-voice")
        self._thread.start()

        # Discover in background, show overlay on main thread when done
        def _discover_and_show():
            print("[chunks] Starting discovery...")
            elements = _discover_clickable_elements()
            print(f"[chunks] Discovery done: {len(elements)} elements, stop={self._stop.is_set()}")
            if self._stop.is_set():
                print("[chunks] Aborted — mode was stopped during discovery")
                return
            self._elements = elements
            count = len(elements)
            print(f"[chunks] Mode enabled (say 1-{count})" if count else "[chunks] Mode enabled (no elements found)")
            print("[chunks] Dispatching overlay to main thread...")
            _dispatch_to_main(lambda: self._overlay.showWithElements_(elements))

        threading.Thread(target=_discover_and_show, daemon=True, name="chunks-discover").start()

    def stop(self):
        if not self.running:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        self._overlay.hide()
        self._queue = None
        self._elements = []
        print("[chunks] Mode disabled")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self):
        while not self._stop.is_set():
            if self._queue is None:
                break
            try:
                text = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            n = _extract_number(text)
            if n is None:
                continue
            if not (1 <= n <= len(self._elements)):
                print(f"[chunks] Ignoring out-of-range number: {n} (have {len(self._elements)} elements)")
                continue
            self._click_element(n)

    def _click_element(self, n: int):
        elem = self._elements[n - 1]
        x = elem.center_x
        y = elem.center_y
        self._cursor.move(x, y)
        self._cursor.click()
        label = f" ({elem.label})" if elem.label else ""
        print(f"[chunks] Clicked #{n} {elem.role}{label} at ({x:.0f}, {y:.0f})")

        # Refresh overlay after click (UI may have changed)
        if self._stop.is_set():
            return
        time.sleep(_POST_CLICK_DELAY)
        if self._stop.is_set():
            return
        new_elements = _discover_clickable_elements()
        self._elements = new_elements
        # Dispatch overlay refresh to main thread
        _dispatch_to_main(lambda elems=new_elements: self._overlay.showWithElements_(elems))


# -- Voice number parsing (reused from original) ---------------------------

_UNITS = {
    "zero": 0,
    "oh": 0,
    "one": 1,
    "won": 1,
    "two": 2,
    "to": 2,
    "too": 2,
    "three": 3,
    "four": 4,
    "for": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "ate": 8,
    "nine": 9,
}

_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _extract_number(text: str) -> int | None:
    if not text:
        return None
    t = text.lower()
    m = re.search(r"\b(\d{1,3})\b", t)
    if m:
        return int(m.group(1))

    tokens = re.findall(r"[a-z]+", t.replace("-", " "))
    if not tokens:
        return None

    for i, token in enumerate(tokens):
        if token in _TEENS:
            return _TEENS[token]
        if token in _TENS:
            base = _TENS[token]
            if i + 1 < len(tokens) and tokens[i + 1] in _UNITS:
                return base + _UNITS[tokens[i + 1]]
            return base
        if token in _UNITS:
            return _UNITS[token]
    return None
