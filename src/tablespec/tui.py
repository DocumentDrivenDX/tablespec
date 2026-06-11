"""Interactive TUI for UMF exploration and editing.

.. warning:: **Experimental** — This module is governed by FEAT-023
   (authoring tools), but its API may change without notice. Use at your
   own risk.

Provides a Textual-based terminal UI for browsing UMF schemas, searching
across columns, and performing inline edits. Requires the `tui` extra:

    pip install tablespec[tui]

Launch via CLI:

    tablespec explore path/to/umf/

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static, TextArea, Tree


# ---------------------------------------------------------------------------
# Data helpers (pure Python, no Textual dependency for testing)
# ---------------------------------------------------------------------------

def load_umfs_from_path(path: Path) -> list[dict[str, Any]]:
    """Load UMF data from a file or directory of YAML files.

    Returns a list of raw dicts (not Pydantic models) so we can round-trip
    edit them with ruamel.yaml without losing comments or ordering.
    """
    yaml = YAML()
    yaml.preserve_quotes = True

    results: list[dict[str, Any]] = []
    path = Path(path)

    if path.is_file() and path.suffix in {".yaml", ".yml"}:
        with path.open() as f:
            data = yaml.load(f)
        if data and "columns" in data:
            data["_source_path"] = str(path)
            results.append(data)
    elif path.is_dir():
        # Look for YAML files that contain UMF data (have a 'columns' key)
        for yaml_file in sorted(path.glob("*.yaml")):
            try:
                with yaml_file.open() as f:
                    data = yaml.load(f)
                if data and "columns" in data:
                    data["_source_path"] = str(yaml_file)
                    results.append(data)
            except Exception:
                continue
        # Also support .yml extension
        for yaml_file in sorted(path.glob("*.yml")):
            try:
                with yaml_file.open() as f:
                    data = yaml.load(f)
                if data and "columns" in data:
                    data["_source_path"] = str(yaml_file)
                    results.append(data)
            except Exception:
                continue
    return results


def _nullable_badge(col: dict[str, Any]) -> str:
    """Return a compact nullable badge string for a column."""
    nullable = col.get("nullable")
    if nullable is None:
        return "nullable"
    if isinstance(nullable, dict):
        vals = list(nullable.values())
        if all(v is False for v in vals):
            return "NOT NULL"
        if all(v is True for v in vals):
            return "nullable"
        # Mixed: show per-context
        parts = [f"{k}:{'Y' if v else 'N'}" for k, v in nullable.items()]
        return " ".join(parts)
    return "nullable"


def _format_column_detail(col: dict[str, Any]) -> str:
    """Format full column details for the detail panel."""
    lines: list[str] = []
    lines.append(f"Column: {col.get('name', '?')}")
    lines.append(f"Type:   {col.get('data_type', '?')}")

    if col.get("canonical_name"):
        lines.append(f"Canonical: {col['canonical_name']}")
    if col.get("description"):
        lines.append(f"Description: {col['description']}")
    if col.get("domain_type"):
        lines.append(f"Domain Type: {col['domain_type']}")
    if col.get("format"):
        lines.append(f"Format: {col['format']}")

    # Nullable
    lines.append(f"Nullable: {_nullable_badge(col)}")

    # Size info
    if col.get("length"):
        lines.append(f"Length: {col['length']}")
    if col.get("precision"):
        p = col["precision"]
        s = col.get("scale", 0)
        lines.append(f"Precision: {p}, Scale: {s}")

    if col.get("source"):
        lines.append(f"Source: {col['source']}")
    if col.get("key_type"):
        lines.append(f"Key Type: {col['key_type']}")
    if col.get("sample_values"):
        lines.append(f"Sample Values: {', '.join(str(v) for v in col['sample_values'][:5])}")
    if col.get("notes"):
        for note in col["notes"]:
            lines.append(f"Note: {note}")

    # Profiling data
    profiling = col.get("profiling")
    if profiling:
        lines.append("")
        lines.append("--- Profiling ---")
        if "completeness" in profiling:
            lines.append(f"  Completeness: {profiling['completeness']:.1%}")
        if "approximate_num_distinct" in profiling:
            lines.append(f"  Distinct: ~{profiling['approximate_num_distinct']}")
        if "num_records" in profiling:
            lines.append(f"  Records: {profiling['num_records']}")
        stats = profiling.get("statistics", {})
        if stats:
            for k, v in stats.items():
                lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def _matches_search(col: dict[str, Any], query: str) -> bool:
    """Check if a column matches a search query (name, domain_type, description)."""
    q = query.lower()
    name = (col.get("name") or "").lower()
    desc = (col.get("description") or "").lower()
    domain = (col.get("domain_type") or "").lower()
    dtype = (col.get("data_type") or "").lower()
    return q in name or q in desc or q in domain or q in dtype


# ---------------------------------------------------------------------------
# Textual App
# ---------------------------------------------------------------------------

TCSS = """\
#main-layout {
    layout: horizontal;
    height: 1fr;
}

#tree-panel {
    width: 1fr;
    min-width: 30;
    max-width: 60;
    border-right: solid $accent;
    overflow-y: auto;
}

#detail-panel {
    width: 2fr;
    padding: 1 2;
}

#detail-view {
    height: 1fr;
    overflow-y: auto;
}

#edit-area {
    display: none;
    height: 1fr;
}

#search-bar {
    dock: top;
    height: 3;
    padding: 0 1;
}
"""


class UMFExplorer(App):
    """Interactive TUI for exploring and editing UMF schemas."""

    CSS = TCSS
    TITLE = "UMF Explorer"

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+f", "focus_search", "Search"),
        Binding("e", "edit", "Edit", show=True),
        Binding("escape", "cancel_edit", "Cancel Edit", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._umfs: list[dict[str, Any]] = []
        # Track which column is selected: (umf_index, column_index)
        self._selected: tuple[int, int] | None = None
        self._editing = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search columns (name, type, description)...", id="search-bar")
        with Horizontal(id="main-layout"):
            yield Tree("UMF Tables", id="tree-panel")
            with Vertical(id="detail-panel"):
                yield Static("Select a column to view details.", id="detail-view")
                yield TextArea(id="edit-area")
        yield Footer()

    def on_mount(self) -> None:
        self._umfs = load_umfs_from_path(self._path)
        self._populate_tree()

    def _populate_tree(self, query: str = "") -> None:
        """Populate the tree widget with UMF tables and columns."""
        tree: Tree = self.query_one("#tree-panel", Tree)  # type: ignore[type-arg]
        tree.clear()

        for umf_idx, umf in enumerate(self._umfs):
            table_name = umf.get("table_name", f"Table {umf_idx}")
            desc = umf.get("description", "")
            label = table_name
            if desc:
                label += f" - {desc[:40]}"
            table_node = tree.root.add(label, expand=True)
            table_node.data = ("table", umf_idx)

            columns = umf.get("columns", [])
            for col_idx, col in enumerate(columns):
                if query and not _matches_search(col, query):
                    continue
                col_name = col.get("name", "?")
                col_type = col.get("data_type", "?")
                badge = _nullable_badge(col)
                col_label = f"{col_name}  [{col_type}]  ({badge})"
                col_node = table_node.add_leaf(col_label)
                col_node.data = ("column", umf_idx, col_idx)

        tree.root.expand()

    @on(Tree.NodeSelected)
    def _on_tree_select(self, event: Tree.NodeSelected) -> None:  # type: ignore[type-arg]
        node = event.node
        if node.data is None:
            return
        if node.data[0] == "column":
            _, umf_idx, col_idx = node.data
            self._selected = (umf_idx, col_idx)
            col = self._umfs[umf_idx]["columns"][col_idx]
            detail = _format_column_detail(col)
            self.query_one("#detail-view", Static).update(detail)
            # If editing, cancel
            if self._editing:
                self._cancel_edit()

    @on(Input.Changed, "#search-bar")
    def _on_search(self, event: Input.Changed) -> None:
        self._populate_tree(query=event.value)

    def action_focus_search(self) -> None:
        self.query_one("#search-bar", Input).focus()

    def action_edit(self) -> None:
        """Enter edit mode for the selected column's description and data_type."""
        if self._selected is None:
            self.notify("No column selected.", severity="warning")
            return
        umf_idx, col_idx = self._selected
        col = self._umfs[umf_idx]["columns"][col_idx]

        # Build editable text (description + data_type)
        desc = col.get("description") or ""
        dtype = col.get("data_type") or ""
        edit_text = f"description: {desc}\ndata_type: {dtype}"

        edit_area = self.query_one("#edit-area", TextArea)
        edit_area.load_text(edit_text)
        edit_area.display = True
        edit_area.focus()
        self.query_one("#detail-view", Static).display = False
        self._editing = True

    def _cancel_edit(self) -> None:
        edit_area = self.query_one("#edit-area", TextArea)
        edit_area.display = False
        self.query_one("#detail-view", Static).display = True
        self._editing = False

    def action_cancel_edit(self) -> None:
        if self._editing:
            self._cancel_edit()

    def action_save(self) -> None:
        """Save edits back to the YAML file (Ctrl+S)."""
        if not self._editing or self._selected is None:
            self.notify("Nothing to save.", severity="warning")
            return
        self._do_save()

    @work(thread=True)
    def _do_save(self) -> None:
        """Perform the save in a worker thread to avoid blocking the UI."""
        if self._selected is None:
            return
        umf_idx, col_idx = self._selected

        edit_area = self.query_one("#edit-area", TextArea)
        text = edit_area.text

        # Parse the edited fields
        new_desc: str | None = None
        new_dtype: str | None = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("description:"):
                new_desc = line[len("description:"):].strip()
            elif line.startswith("data_type:"):
                new_dtype = line[len("data_type:"):].strip()

        umf = self._umfs[umf_idx]
        col = umf["columns"][col_idx]

        changed = False
        if new_desc is not None and new_desc != (col.get("description") or ""):
            col["description"] = new_desc
            changed = True
        if new_dtype is not None and new_dtype != (col.get("data_type") or ""):
            col["data_type"] = new_dtype
            changed = True

        if changed:
            source_path = umf.get("_source_path")
            if source_path:
                self._save_yaml(Path(source_path), umf)
                self.call_from_thread(
                    self.notify, f"Saved changes to {Path(source_path).name}"
                )
            else:
                self.call_from_thread(
                    self.notify, "No source path - cannot save.", severity="error"
                )
        else:
            self.call_from_thread(self.notify, "No changes detected.")

        # Exit edit mode and refresh
        self.call_from_thread(self._cancel_edit)
        self.call_from_thread(self._refresh_detail)

    def _refresh_detail(self) -> None:
        """Refresh the detail panel for the currently selected column."""
        if self._selected is None:
            return
        umf_idx, col_idx = self._selected
        col = self._umfs[umf_idx]["columns"][col_idx]
        self.query_one("#detail-view", Static).update(_format_column_detail(col))
        # Also refresh tree labels
        self._populate_tree()

    @staticmethod
    def _save_yaml(path: Path, umf_data: dict[str, Any]) -> None:
        """Round-trip save a UMF dict back to YAML, preserving comments."""
        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.default_flow_style = False
        yaml.width = 100

        # Load existing file for round-trip preservation
        with path.open() as f:
            existing = yaml.load(f)

        if existing is None:
            existing = {}

        # Update only the columns we changed
        if "columns" in umf_data and "columns" in existing:
            for i, col in enumerate(umf_data["columns"]):
                if i < len(existing["columns"]):
                    existing["columns"][i]["description"] = col.get("description")
                    existing["columns"][i]["data_type"] = col.get("data_type")

        with path.open("w") as f:
            yaml.dump(existing, f)
