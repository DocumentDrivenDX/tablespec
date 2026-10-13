"""Format changelog entries for display and export."""

from datetime import datetime

from rich.console import Console
from rich.table import Table as RichTable

from tablespec.models.changelog import ChangeEntry, ChangeType


def format_changelog_console(
    entries: list[ChangeEntry],
    console: Console | None = None,
    detailed: bool = False,
) -> None:
    """Display changelog with rich console formatting.

    Args:
        entries: List of changelog entries
        console: Rich console instance (uses default if None)
        detailed: Show detailed change information

    """
    if console is None:
        console = Console()

    if not entries:
        console.print("[dim]No changelog entries found[/dim]")
        return

    for entry in entries:
        # Format date and commit info
        date_str = entry.commit_date.strftime("%Y-%m-%d %H:%M")
        commit_str = entry.commit_hash
        author_str = entry.author_name

        table_context = f" [{entry.table_name}]" if entry.table_name else ""
        console.print(
            f"📅 {date_str} | [cyan]{commit_str}[/cyan] | {author_str}{table_context}",
            style="bold",
        )

        # Summary line (already contains review note as commit message)
        console.print(f"├─ {entry.summary}")

        # Extract detailed change info from commit message body if present
        # Format: "Changes in <table>:\n- <change1>\n- <change2>"
        body_changes = _extract_commit_body_changes(entry.commit_message)

        if detailed and body_changes:
            console.print()
            console.print("│  [cyan]Changes:[/cyan]")
            for line in body_changes:
                console.print(f"│  • {line}")
            console.print()

        # Files changed
        if detailed and entry.files_changed:
            console.print("│  [dim]Files:[/dim]")
            for file_path in entry.files_changed:
                console.print(f"│    • {file_path}")
            console.print()

        # If no body changes, fall back to YAML diff changes
        if detailed and not body_changes and entry.changes:
            console.print("│  [cyan]Change Details:[/cyan]")
            for change in entry.changes:
                change_icon = _get_change_icon(change.change_type)
                console.print(f"│  {change_icon} {change.description}")

        console.print("└─")
        console.print()


def format_changelog_markdown(entries: list[ChangeEntry]) -> str:
    """Export changelog to markdown format.

    Args:
        entries: List of changelog entries

    Returns:
        Markdown-formatted changelog

    """
    if not entries:
        return "# Changelog\n\nNo entries found."

    lines = ["# Changelog\n"]

    for entry in entries:
        # Date and commit header
        date_str = entry.commit_date.strftime("%Y-%m-%d")
        lines.append(f"## {date_str} - {entry.commit_hash}\n")

        # Author
        lines.append(f"**Author:** {entry.author_name} <{entry.author_email}>\n")

        # Summary (already contains review note as commit message)
        lines.append(f"**Summary:** {entry.summary}\n")

        # Changes
        if entry.changes:
            lines.append("### Changes\n")
            for change in entry.changes:
                lines.append(f"- {change.description}")
                if change.affected_item:
                    lines.append(f"  - Item: `{change.affected_item}`")

            lines.append("")

        # Files
        if entry.files_changed:
            lines.append("### Files Changed\n")
            for file_path in entry.files_changed:
                lines.append(f"- `{file_path}`")
            lines.append("")

        lines.append("---\n")

    return "\n".join(lines)


def format_changelog_json(entries: list[ChangeEntry]) -> dict:
    """Export changelog to JSON format.

    Args:
        entries: List of changelog entries

    Returns:
        Dictionary suitable for json.dumps()

    """
    return {
        "changelog": [
            {
                "commit_hash": entry.commit_hash,
                "commit_date": entry.commit_date.isoformat(),
                "author": {
                    "name": entry.author_name,
                    "email": entry.author_email,
                },
                "message": entry.commit_message,
                "review_note": entry.review_note,
                "changes": [
                    {
                        "type": change.change_type.value,
                        "description": change.description,
                        "affected_item": change.affected_item,
                        "old_value": change.old_value,
                        "new_value": change.new_value,
                        "file_path": change.file_path,
                    }
                    for change in entry.changes
                ],
                "files_changed": entry.files_changed,
            }
            for entry in entries
        ],
        "generated_at": datetime.now().isoformat(),
    }


def format_changelog_table(
    entries: list[ChangeEntry],
    console: Console | None = None,
    limit: int = 10,
) -> None:
    """Display changelog in table format.

    Args:
        entries: List of changelog entries
        console: Rich console instance (uses default if None)
        limit: Maximum entries to display

    """
    if console is None:
        console = Console()

    if not entries:
        console.print("[dim]No changelog entries found[/dim]")
        return

    table = RichTable(show_header=True, show_lines=False)
    table.add_column("Date", style="cyan")
    table.add_column("Commit", style="magenta")
    table.add_column("Author", style="green")
    table.add_column("Summary")
    table.add_column("Changes", justify="center")

    for entry in entries[:limit]:
        date_str = entry.commit_date.strftime("%Y-%m-%d")
        change_count = len(entry.changes)

        summary = (
            entry.summary[:50] + "..." if len(entry.summary) > 50 else entry.summary
        )

        table.add_row(
            date_str,
            entry.commit_hash,
            entry.author_name,
            summary,
            str(change_count),
        )

    console.print(table)

    if len(entries) > limit:
        console.print(f"[dim]... and {len(entries) - limit} more entries[/dim]")


def _extract_commit_body_changes(commit_message: str) -> list[str]:
    """Extract change details from commit message body.

    Looks for lines starting with "- " after "Changes in <table>:" header.

    Args:
        commit_message: Full commit message

    Returns:
        List of change description lines (without leading "- ")

    """
    lines = commit_message.split("\n")
    changes = []
    in_changes_section = False

    for line in lines:
        # Start of changes section
        if line.startswith("Changes in "):
            in_changes_section = True
            continue

        # End of changes section (empty line or new section)
        if in_changes_section and (
            not line.strip() or line.startswith(("Source:", "Imported:"))
        ):
            break

        # Extract change lines (start with "- ")
        if in_changes_section and line.startswith("- "):
            changes.append(line[2:])  # Remove "- " prefix

    return changes


def _get_change_icon(change_type: ChangeType) -> str:
    """Get emoji icon for change type.

    Args:
        change_type: Type of change

    Returns:
        Emoji icon string

    """
    icons = {
        ChangeType.COLUMN_ADDED: "➕",
        ChangeType.COLUMN_REMOVED: "➖",
        ChangeType.COLUMN_MODIFIED: "✏️",
        ChangeType.VALIDATION_ADDED: "➕",
        ChangeType.VALIDATION_REMOVED: "➖",
        ChangeType.VALIDATION_MODIFIED: "✏️",
        ChangeType.RELATIONSHIP_ADDED: "🔗",
        ChangeType.RELATIONSHIP_REMOVED: "🔗",
        ChangeType.RELATIONSHIP_MODIFIED: "🔗",
        ChangeType.METADATA_CHANGED: "📝",
        ChangeType.FILE_FORMAT_CHANGED: "⚙️",
        ChangeType.OTHER: "•",
    }
    return icons.get(change_type, "•")
