"""Generate changelog from git history for tablespecs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

import git

from tablespec.changelog_diff_parser import (
    YAMLDiffParser,
)
from tablespec.models.changelog import ChangeDetail, ChangeEntry, ChangeType


class ChangelogGenerator:
    """Generate changelog from git history for a table directory."""

    # Regex patterns for detecting change types from file paths
    COLUMN_FILES = re.compile(r"columns/")
    VALIDATION_FILES = re.compile(r"validation/")
    RELATIONSHIP_FILES = re.compile(r"relationships/")
    FILE_FORMAT_FILES = re.compile(r"file_format\.yaml")
    METADATA_FILES = re.compile(r"metadata\.yaml")

    def __init__(self, table_dir: Path) -> None:
        """Initialize changelog generator for a table directory.

        Args:
            table_dir: Path to table directory (e.g., pipelines/testdata/outreach_list)

        Raises:
            ValueError: If table_dir is not in a git repository or doesn't exist
            ImportError: If GitPython is not installed or git executable is not available

        """
        try:
            import git
        except ImportError as e:
            msg = (
                "GitPython or git executable not available. "
                "Install with: pip install GitPython, "
                "and ensure git is in your PATH"
            )
            raise ImportError(msg) from e

        self.table_dir = Path(table_dir)

        if not self.table_dir.exists():
            msg = f"Table directory not found: {table_dir}"
            raise ValueError(msg)

        try:
            self.repo = git.Repo(self.table_dir, search_parent_directories=True)
        except git.InvalidGitRepositoryError as e:
            msg = f"Table directory not in a git repository: {table_dir}"
            raise ValueError(msg) from e

        self.diff_parser = YAMLDiffParser()

    def generate_changelog(
        self,
        limit: int | None = None,
        since: str | None = None,
    ) -> list[ChangeEntry]:
        """Generate changelog entries from git history.

        Args:
            limit: Maximum number of commits to include (None for all)
            since: Git date specification (e.g., "2 weeks ago", "2025-10-01")

        Returns:
            List of ChangeEntry objects, newest first

        Raises:
            git.GitCommandError: If git command fails

        """
        entries = []

        try:
            # Get relative path from repo root to table directory
            rel_path = self.table_dir.relative_to(self.repo.working_dir)

            # Build git log arguments
            # Note: iter_commits doesn't support "follow" well with directories
            # Use raw git command instead for better control
            kwargs: dict[str, Any] = {
                "reverse": False,  # Newest first
            }

            if since:
                kwargs["since"] = since

            if limit:
                kwargs["max_count"] = limit

            # Get commits affecting this directory
            # Pass paths as a tuple for directory history
            commits = list(self.repo.iter_commits(paths=str(rel_path), **kwargs))

            # Process each commit
            for commit in commits:
                # Get files changed in this commit that affect our table
                affected_files = self._get_affected_files(commit)

                if not affected_files:
                    continue

                # Detect changes from affected files
                changes = self._detect_changes(commit, affected_files)

                # Extract review note from commit message
                commit_msg = (
                    commit.message
                    if isinstance(commit.message, str)
                    else commit.message.decode()
                )
                review_note = self._extract_review_note(commit_msg)

                # Create entry
                author_name = commit.author.name or "Unknown"
                author_email = commit.author.email or "unknown@example.com"
                entry = ChangeEntry(
                    commit_hash=commit.hexsha[:8],
                    commit_date=datetime.fromtimestamp(commit.committed_date, tz=UTC),
                    author_name=author_name,
                    author_email=author_email,
                    commit_message=commit_msg,
                    review_note=review_note,
                    files_changed=[str(f) for f in affected_files],
                    changes=changes,
                    table_name=self.table_dir.name,
                )

                entries.append(entry)

            # Reverse to get newest first
            return list(reversed(entries))

        except git.GitCommandError as e:
            msg = f"Failed to generate changelog: {e}"
            raise ValueError(msg) from e

    def _get_affected_files(self, commit: git.Commit) -> list[Path]:
        """Get files affected by commit that are in table directory.

        Args:
            commit: Git commit object

        Returns:
            List of relative paths from repo root

        """
        affected = []

        try:
            rel_path = self.table_dir.relative_to(self.repo.working_dir)

            parent_commit = commit.parents[0] if commit.parents else None
            for diff_item in commit.diff(parent_commit):
                file_path = diff_item.b_path or diff_item.a_path
                if not file_path:
                    continue
                changed_file = Path(file_path)

                # Check if file is in our table directory
                try:
                    changed_file.relative_to(rel_path)
                    affected.append(changed_file)
                except ValueError:
                    # File not in table directory
                    pass

        except (IndexError, AttributeError):
            # Handle commits with no parents (initial commit)
            pass

        return affected

    def _detect_changes(
        self,
        commit: git.Commit,
        affected_files: list[Path],
    ) -> list[ChangeDetail]:
        """Detect semantic changes from affected files using YAML diffing.

        Args:
            commit: Git commit object
            affected_files: List of affected file paths

        Returns:
            List of ChangeDetail objects with detailed change descriptions

        """
        changes = []

        for file_path in affected_files:
            file_str = str(file_path)

            # Get file content before/after
            try:
                old_content, new_content = self._get_file_diff(commit, file_path)
            except Exception:
                # Fallback to generic change if diff fails
                changes.append(
                    ChangeDetail(
                        change_type=ChangeType.OTHER,
                        description=f"Modified {file_path.name}",
                    )
                )
                continue

            # Parse specific changes based on file type
            if self.VALIDATION_FILES.search(file_str):
                validation_changes = self.diff_parser.parse_validation_changes(
                    old_content,
                    new_content,
                    table_name=self.table_dir.name,
                )
                for vc in validation_changes:
                    changes.append(
                        ChangeDetail(
                            change_type=ChangeType.VALIDATION_MODIFIED,
                            description=vc.format_description(),
                            affected_item=None,
                            file_path=file_str,
                        )
                    )

            elif self.COLUMN_FILES.search(file_str):
                column_changes = self.diff_parser.parse_column_changes(
                    old_content,
                    new_content,
                    table_name=self.table_dir.name,
                )
                for cc in column_changes:
                    changes.append(
                        ChangeDetail(
                            change_type=ChangeType.COLUMN_MODIFIED,
                            description=cc.format_description(),
                            affected_item=cc.column_name,
                            old_value=str(cc.old_value)
                            if cc.old_value is not None
                            else None,
                            new_value=str(cc.new_value)
                            if cc.new_value is not None
                            else None,
                            file_path=file_str,
                        )
                    )

            elif self.RELATIONSHIP_FILES.search(file_str):
                relationship_changes = self.diff_parser.parse_relationship_changes(
                    old_content,
                    new_content,
                    table_name=self.table_dir.name,
                )
                for rc in relationship_changes:
                    # Determine change type based on field
                    if rc.change_field == "added":
                        change_type = ChangeType.RELATIONSHIP_ADDED
                    elif rc.change_field == "removed":
                        change_type = ChangeType.RELATIONSHIP_REMOVED
                    else:
                        change_type = ChangeType.RELATIONSHIP_MODIFIED

                    changes.append(
                        ChangeDetail(
                            change_type=change_type,
                            description=rc.format_description(),
                            affected_item=rc.fk_column,
                            old_value=str(rc.old_value)
                            if rc.old_value is not None
                            else None,
                            new_value=str(rc.new_value)
                            if rc.new_value is not None
                            else None,
                            file_path=file_str,
                        )
                    )

            elif self.METADATA_FILES.search(file_str):
                metadata_changes = self.diff_parser.parse_metadata_changes(
                    old_content,
                    new_content,
                )
                for mc in metadata_changes:
                    changes.append(
                        ChangeDetail(
                            change_type=ChangeType.METADATA_CHANGED,
                            description=mc.format_description(),
                            affected_item=mc.change_field,
                            old_value=str(mc.old_value)
                            if mc.old_value is not None
                            else None,
                            new_value=str(mc.new_value)
                            if mc.new_value is not None
                            else None,
                            file_path=file_str,
                        )
                    )

            elif "derivations" in file_str:
                derivation_changes = self.diff_parser.parse_derivation_changes(
                    old_content,
                    new_content,
                    table_name=self.table_dir.name,
                )
                for dc in derivation_changes:
                    changes.append(
                        ChangeDetail(
                            change_type=ChangeType.OTHER,
                            description=dc.format_description(),
                            affected_item=dc.target_column,
                            old_value=str(dc.old_value)
                            if dc.old_value is not None
                            else None,
                            new_value=str(dc.new_value)
                            if dc.new_value is not None
                            else None,
                            file_path=file_str,
                        )
                    )

            elif self.FILE_FORMAT_FILES.search(file_str):
                changes.append(
                    ChangeDetail(
                        change_type=ChangeType.FILE_FORMAT_CHANGED,
                        description="Updated file format configuration",
                        file_path=file_str,
                    )
                )

            else:
                changes.append(
                    ChangeDetail(
                        change_type=ChangeType.OTHER,
                        description=f"Modified {file_path.name}",
                        file_path=file_str,
                    )
                )

        return changes

    def _get_file_diff(
        self,
        commit: git.Commit,
        file_path: Path,
    ) -> tuple[str, str]:
        """Get old and new content for a file from commit.

        Args:
            commit: Git commit object
            file_path: Path to file (may be relative to repo root or absolute)

        Returns:
            Tuple of (old_content, new_content) as strings

        """
        # Ensure path is relative to repo root
        try:
            if file_path.is_absolute():
                rel_path = file_path.relative_to(self.repo.working_dir)
            else:
                rel_path = file_path
            rel_path_parts = rel_path.parts
        except ValueError:
            return ("", "")

        # Get parent commit
        parent_commit = commit.parents[0] if commit.parents else None

        # Get old content
        old_content = ""
        if parent_commit:
            try:
                old_tree: Any = parent_commit.tree
                for part in rel_path_parts:
                    old_tree = old_tree / part
                old_content = old_tree.data_stream.read().decode("utf-8")
            except (KeyError, AttributeError, TypeError):
                old_content = ""

        # Get new content
        new_content = ""
        try:
            new_tree: Any = commit.tree
            for part in rel_path_parts:
                new_tree = new_tree / part
            new_content = new_tree.data_stream.read().decode("utf-8")
        except (KeyError, AttributeError, TypeError):
            new_content = ""

        return old_content, new_content

    def _extract_review_note(self, commit_message: str) -> str | None:
        """Extract review note from commit message.

        Looks for "Review Note:" in the commit message body.

        Args:
            commit_message: Full commit message

        Returns:
            Review note text if found, None otherwise

        """
        lines = commit_message.split("\n")

        for i, line in enumerate(lines):
            if line.startswith("Review Note:"):
                # Extract text after "Review Note:"
                text = line[len("Review Note:") :].strip()

                # If text continues on next lines, include them
                if text:
                    return text

                # Otherwise, check if note is on following lines
                if i + 1 < len(lines):
                    # Collect lines until we hit another field or empty line
                    note_lines = []
                    for next_line in lines[i + 1 :]:
                        if next_line.startswith(
                            ("Rule ID:", "Column:", "Type:", "Severity:")
                        ):
                            break
                        if next_line.strip():
                            note_lines.append(next_line.strip())

                    if note_lines:
                        return " ".join(note_lines)

        return None
