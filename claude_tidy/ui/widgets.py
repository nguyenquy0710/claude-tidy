"""Shared Treeview-with-checkboxes widget used by Explorer, Cache, Index and
the delete-flow preview dialog — one implementation instead of four ad-hoc
Tk checkbox hacks.

`ttk.Treeview` has no native checkbox column, so this fakes one with a
Unicode glyph in a dedicated column and a click/Space handler that toggles
it. Nesting (project -> worktree) is native Treeview parent/child, so the
expand/collapse arrow comes for free.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import ttkbootstrap as tb

UNCHECKED = "☐"  # ☐
CHECKED = "☑"  # ☑
CHECK_COLUMN = "_check"


class CheckTreeview(tb.Frame):
    def __init__(
        self,
        master,
        columns: Iterable[str],
        headings: dict[str, str] | None = None,
        on_change: Callable[[str, bool], None] | None = None,
        on_activate: Callable[[str], None] | None = None,
        show_checkboxes: bool = True,
        **kw,
    ) -> None:
        super().__init__(master)
        self.on_change = on_change
        self.on_activate = on_activate
        self.show_checkboxes = show_checkboxes
        self._checked: set[str] = set()
        self._checkable: set[str] = set()

        all_columns = (CHECK_COLUMN, *columns) if show_checkboxes else tuple(columns)
        self.tree = tb.Treeview(self, columns=all_columns, show="tree headings", **kw)
        if show_checkboxes:
            self.tree.heading(CHECK_COLUMN, text="")
            self.tree.column(CHECK_COLUMN, width=32, anchor="center", stretch=False)
        for name in columns:
            self.tree.heading(name, text=(headings or {}).get(name, name))

        vsb = tb.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

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
        row_values = (UNCHECKED if checkable else "", *values) if self.show_checkboxes else values
        self.tree.insert(parent, "end", iid=iid, text=text, values=row_values, tags=tags,
                         open=open_)
        if checkable:
            self._checkable.add(iid)
        return iid

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())
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
        symbol = CHECKED if value else UNCHECKED
        values = list(self.tree.item(iid, "values"))
        values[0] = symbol
        self.tree.item(iid, values=values)
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
