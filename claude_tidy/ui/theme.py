"""Design tokens sampled from the reference mockup's real computed CSS
(docs/claude-tidy — UI.html), not eyeballed from a screenshot — every value
here was read via `getComputedStyle()` in a live browser. One place for the
whole app so a color never drifts between modules.

See claude_tidy/ui/CLAUDE.md "Visual design source of truth" for the
disclosed, unavoidable gaps (font not installed, no per-cell pill badges,
no custom title bar).
"""

from __future__ import annotations

import contextlib
import tkinter as tk
import tkinter.font as tkfont

# Colors — hex, sampled from the mockup's `getComputedStyle()` output.
BODY_BG = "#e9ecf0"
PANEL_BG = "#f8f9fb"
BORDER = "#cfd5dc"
BORDER_LIGHT = "#dde1e6"
TEXT_DARK = "#1c2430"
TEXT_MUTED = "#5b6573"
ACCENT = "#1f6fc5"
DANGER_FG = "#b3261e"
WARNING_BG = "#fdf0d2"
WARNING_FG = "#7a5200"

# The mockup's own CSS names "IBM Plex Sans" (with a system-ui/sans-serif
# fallback chain) — not installed on this dev machine (see
# claude_tidy/ui/CLAUDE.md). Falls back to Segoe UI, Tk's own Windows
# default and also a humanist sans — but a machine that *does* have IBM Plex
# Sans installed picks it up automatically.
_FONT_CANDIDATES = ("IBM Plex Sans", "Segoe UI")
_resolved_family: str | None = None


def resolve_font_family() -> str:
    available = set(tkfont.families())
    for name in _FONT_CANDIDATES:
        if name in available:
            return name
    return "TkDefaultFont"


def font_family() -> str:
    """The family resolved by `apply_global_style()`.

    A plain `font=("", size, "bold")` tuple does **not** inherit the
    `TkDefaultFont` override below — Tk resolves an empty family name to its
    own built-in default (Arial), silently ignoring the configured family.
    Every explicit font tuple in this package must use this getter instead
    of `""`. Callable only after `apply_global_style()` has run (i.e. from
    inside a widget constructor, never at module import time — no Tk root
    exists yet then).
    """
    if _resolved_family is None:
        raise RuntimeError("font_family() called before apply_global_style()")
    return _resolved_family


def apply_global_style(root: tk.Misc) -> str:
    """Apply the sampled palette app-wide. Must run right after the ttkbootstrap
    `Window`/`Style` is created and before any other widget — `Style.colors.set()`
    only affects bootstyle-generated styles created *after* the call. Returns
    the resolved font family so callers can reuse it for one-off labels
    (`explorer.py`'s stat blocks, headings, etc.) instead of hardcoding a size
    tuple with no family.
    """
    global _resolved_family
    import ttkbootstrap as tb

    style = tb.Style()
    # Retint the theme's own color tokens instead of fighting raw ttk.Style
    # per-widget — every existing `bootstyle="primary"`/`"danger"`/etc. call
    # site across the app picks up the exact mockup color for free.
    style.colors.set("primary", ACCENT)
    style.colors.set("danger", DANGER_FG)
    style.colors.set("secondary", TEXT_MUTED)
    style.colors.set("warning", WARNING_FG)
    style.colors.set("light", PANEL_BG)
    style.colors.set("border", BORDER)

    family = resolve_font_family()
    _resolved_family = family
    for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont",
                "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont"):
        with contextlib.suppress(tk.TclError):
            tkfont.nametofont(name).configure(family=family)

    # Only the window's own background goes gray (visible in the outer
    # padding/notebook gaps) — NOT a blanket TFrame/TLabel override. Every
    # bootstyle (e.g. "secondary") generates its own named style with its
    # own background baked in by ttkbootstrap; forcing TFrame/TLabel to
    # BODY_BG fights that and leaves mismatched-colored rectangles wherever
    # a bootstyled label sits on a plain frame (or vice versa) — this was
    # tried and visibly broke the stat-block labels in explorer.py.
    root.configure(background=BODY_BG)
    style.configure(".", font=(family, 10), foreground=TEXT_DARK)

    # Table/tree headings: muted gray, small, bold as a stand-in for the
    # mockup's semibold (Tk font weight is only normal/bold) — not the
    # theme's default dark heading text.
    style.configure("Treeview.Heading", font=(family, 9, "bold"), foreground=TEXT_MUTED,
                    background=PANEL_BG)
    style.configure("Treeview", font=(family, 10), fieldbackground="#ffffff")

    # The project sidebar sits on its own off-white panel, distinct from the
    # white main content area — named styles (not a blanket TFrame/TLabel
    # override, see above) applied only to that one panel in explorer.py.
    style.configure("Sidebar.TFrame", background=PANEL_BG)
    style.configure("Sidebar.TLabel", background=PANEL_BG, foreground=TEXT_DARK)
    style.configure("SidebarMuted.TLabel", background=PANEL_BG, foreground=TEXT_MUTED)

    # "Quét lại" and the inactive risk-filter chips are plain neutral buttons
    # in the mockup (white, dark text, gray border) — ttkbootstrap's
    # secondary-outline tints both text and border with the (now muted-gray)
    # secondary color, which reads too flat/disabled-looking by comparison.
    style.configure("Neutral.TButton", font=(family, 9), foreground=TEXT_DARK,
                    background="#ffffff", bordercolor=BORDER, relief="solid",
                    borderwidth=1)
    style.map("Neutral.TButton", background=[("active", "#f3f5f7")],
             bordercolor=[("active", BORDER)])

    return family
