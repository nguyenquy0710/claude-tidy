"""Shared datatable widget used by Explorer, Cache, Index and the delete-flow
preview dialog — one implementation instead of four ad-hoc grids.

Built on ttkbootstrap's ``Tableview`` (a real datatable: click-to-sort
columns, an optional search box, and zebra striping that stays correct after
a re-sort) rather than a bare ``ttk.Treeview``. ``Tableview`` has no native
checkbox column, so this fakes one the same way the earlier
``ttk.Treeview``-only version did: a Unicode glyph in a dedicated first
column, toggled by clicking that column or pressing Space on a selection —
using ``Tableview``'s own internal ``ttk.Treeview`` (its public ``.view``
attribute) for hit-testing, since that part really is still a plain
Treeview underneath.

``Tableview`` has no concept of hierarchy (it's a flat grid), which is fine:
every real caller already passes an empty ``parent`` — none of the four
usages here ever needed nesting. (The one tree that genuinely needs
parent/child nesting, Explorer's *project* list with worktrees grouped under
their parent, stays a plain ``ttk.Treeview`` for that reason — see
`explorer.py`.)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import ttkbootstrap as tb

UNCHECKED = "☐"  # ☐
CHECKED = "☑"  # ☑
LOCKED = "🔒"  # shown instead of a checkbox for a non-checkable row
_IID_COLUMN = "__iid__"  # hidden column Tableview's iid_field is bound to


class CheckTreeview(tb.Frame):
    def __init__(
        self,
        master,
        columns: Iterable[str],
        headings: dict[str, str] | None = None,
        on_change: Callable[[str, bool], None] | None = None,
        on_activate: Callable[[str], None] | None = None,
        show_checkboxes: bool = True,
        searchable: bool = False,
        **kw,
    ) -> None:
        super().__init__(master)
        self.on_change = on_change
        self.on_activate = on_activate
        self.show_checkboxes = show_checkboxes
        self._checked: set[str] = set()
        self._checkable: set[str] = set()

        coldata: list[dict] = []
        if show_checkboxes:
            coldata.append({"text": "", "width": 32, "stretch": False, "anchor": "center"})
        for name in columns:
            coldata.append({"text": (headings or {}).get(name, name), "stretch": True})
        coldata.append({"text": _IID_COLUMN, "width": 0, "stretch": False})

        # No bootstyle/stripecolor override: the reference UI template uses a
        # plain, neutral heading (light gray background, dark text) and no
        # zebra striping — not the accent-colored heading this widget used
        # before that template existed.
        self.table = tb.Tableview(
            self, coldata=coldata, rowdata=[], autofit=False, searchable=searchable,
            yscrollbar=True, iid_field=_IID_COLUMN, **kw,
        )
        self.table.pack(fill="both", expand=True)
        self.table.tablecolumns[-1].hide()

        # Several callers reach into the underlying ttk.Treeview directly
        # (selectmode, extra bindings) — keep that working unchanged.
        self.tree = self.table.view

        if show_checkboxes:
            self.tree.bind("<Button-1>", self._on_click)
            self.tree.bind("<space>", self._on_space)
        if on_activate is not None:
            self.tree.bind("<Double-1>", self._on_double_click)

    def insert_row(
        self,
        parent: str,
        iid: str,
        text: str,
        values: tuple,
        tags: tuple = (),
        checkable: bool = True,
        open_: bool = False,
    ) -> str:
        # `parent`/`text`/`open_` are vestiges of the ttk.Treeview-only API
        # (hierarchy, tree-column label). Tableview is flat, and every real
        # call site already passes "" for both — kept as no-ops so none of
        # them need to change.
        row_values = (
            [UNCHECKED if checkable else LOCKED, *values, iid]
            if self.show_checkboxes else [*values, iid]
        )
        # reload=False: inserting one-by-one with the default reload=True
        # would re-layout the whole table after every single row. Callers
        # call `render()` once after their insert loop instead.
        row = self.table.insert_row(values=row_values, reload=False)
        if tags:
            row.configure(tags=tags)
        if checkable:
            self._checkable.add(iid)
        return iid

    def render(self) -> None:
        """Paint rows queued by `insert_row(..., reload=False)` in one pass."""
        self.table.load_table_data()

    def clear(self) -> None:
        self.table.delete_rows()
        self._checked.clear()
        self._checkable.clear()

    def configure_tag(self, tag: str, **opts) -> None:
        self.tree.tag_configure(tag, **opts)

    def checked_ids(self) -> set[str]:
        return set(self._checked)

    def is_checked(self, iid: str) -> bool:
        return iid in self._checked

    def set_checked(self, iid: str, value: bool) -> None:
        if iid not in self._checkable:
            return
        self._set_checked(iid, value)

    def check_all(self, iids: Iterable[str] | None = None) -> None:
        for iid in (iids if iids is not None else self._checkable):
            if iid in self._checkable:
                self._set_checked(iid, True)

    def uncheck_all(self) -> None:
        for iid in list(self._checked):
            self._set_checked(iid, False)

    def selected_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _set_checked(self, iid: str, value: bool) -> None:
        if value:
            self._checked.add(iid)
        else:
            self._checked.discard(iid)
        row = self.table.get_row(iid=iid)
        if row is not None:
            # Must go through TableRow, not `self.tree.item()` directly:
            # TableRow caches its own `.values` and stamps them back onto
            # the live Treeview on the next `refresh()` (e.g. after a
            # search/filter/reload) — a raw item() write would get silently
            # reverted the next time that happens.
            values = list(row.values)
            values[0] = CHECKED if value else UNCHECKED
            row.values = values
        if self.on_change is not None:
            self.on_change(iid, value)

    def _toggle(self, iid: str) -> None:
        if iid in self._checkable:
            self._set_checked(iid, iid not in self._checked)

    def _on_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":  # the checkbox column
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _on_space(self, _event) -> None:
        for iid in self.tree.selection():
            self._toggle(iid)

    def _on_double_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.show_checkboxes and self.tree.identify_column(event.x) == "#1":
            return  # a checkbox click, not a row activation
        iid = self.tree.identify_row(event.y)
        if iid and self.on_activate is not None:
            self.on_activate(iid)
