# SPDX-License-Identifier: MIT OR Apache-2.0
"""Changelog models for tracking tablespec changes from git history."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ChangeType(str, Enum):
    """Type of change made to a tablespec."""

    COLUMN_ADDED = "column_added"
    COLUMN_REMOVED = "column_removed"
    COLUMN_MODIFIED = "column_modified"

    VALIDATION_ADDED = "validation_added"
    VALIDATION_REMOVED = "validation_removed"
    VALIDATION_MODIFIED = "validation_modified"

    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"
    RELATIONSHIP_MODIFIED = "relationship_modified"

    METADATA_CHANGED = "metadata_changed"
    FILE_FORMAT_CHANGED = "file_format_changed"

    OTHER = "other"


@dataclass
class ChangeDetail:
    """Detailed information about a specific change."""

    change_type: ChangeType
    description: str
    affected_item: str | None = None  # e.g., column name, rule_id
    old_value: str | None = None
    new_value: str | None = None
    file_path: str | None = None  # Path to file affected by this change


@dataclass
class ChangeEntry:
    """Single changelog entry representing a commit with changes."""

    commit_hash: str
    commit_date: datetime
    author_name: str
    author_email: str
    commit_message: str
    review_note: str | None
    files_changed: list[str]
    changes: list[ChangeDetail]
    table_name: str | None = None  # Name of the table being changed

    @property
    def summary(self) -> str:
        """Get first line of commit message (summary)."""
        return self.commit_message.split("\n")[0]

    @property
    def body(self) -> str:
        """Get commit message body (after first line)."""
        lines = self.commit_message.split("\n")
        return "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
