"""Handle git commits during Excel import with review notes."""

from datetime import UTC, datetime
from pathlib import Path

try:
    import git
except ImportError:
    git = None  # type: ignore[assignment]


class ExcelImportCommitter:
    """Manages git commits during Excel import with review notes."""

    def __init__(self, table_dir: Path) -> None:
        """Initialize committer for a table directory.

        Args:
            table_dir: Path to table directory

        Raises:
            ValueError: If not in a git repository
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

        try:
            self.repo = git.Repo(self.table_dir, search_parent_directories=True)
        except git.InvalidGitRepositoryError as e:
            msg = f"Table directory not in a git repository: {table_dir}"
            raise ValueError(msg) from e

    def commit_changes(
        self,
        changed_files: list[Path],
        review_notes: dict[str, str | None],
        summary: str = "Update tablespecs from Excel import",
    ) -> str | None:
        """Create a single commit for Excel import changes.

        Args:
            changed_files: List of files changed by import
            review_notes: Map of component type to review note (e.g., {"validation": "note"})
            summary: Commit message summary

        Returns:
            Commit hash if successful, None if no changes

        Raises:
            ValueError: If git operations fail

        """
        if not changed_files:
            return None

        try:
            # Check if there are actual changes to commit
            diff_index = self.repo.index.diff(None)
            if not diff_index:
                return None

            # Stage the specific files
            rel_files = []
            for file_path in changed_files:
                try:
                    rel_path = file_path.relative_to(self.repo.working_dir)
                    rel_files.append(str(rel_path))
                except ValueError:
                    rel_files.append(str(file_path))

            self.repo.index.add(rel_files)

            # Generate commit message
            commit_msg = self._generate_commit_message(summary, review_notes)

            # Create commit
            commit = self.repo.index.commit(commit_msg)
            return commit.hexsha[:8]

        except git.GitCommandError as e:
            msg = f"Failed to commit changes: {e}"
            raise ValueError(msg) from e

    def commit_single_rule(
        self,
        file_path: Path,
        commit_message: str,
    ) -> str | None:
        """Create a single commit for a validation rule change with review note as message.

        The review note becomes the entire commit message (no technical details appended).
        This creates a clear, human-readable history of rule changes.

        Args:
            file_path: Path to validation file to commit
            commit_message: Review note to use as commit message

        Returns:
            Commit hash if successful, None if no changes

        Raises:
            ValueError: If git operations fail

        """
        try:
            # Check if there are actual changes to commit
            diff_index = self.repo.index.diff(None)
            if not diff_index:
                return None

            # Stage the file
            try:
                rel_path = file_path.relative_to(self.repo.working_dir)
                rel_file = str(rel_path)
            except ValueError:
                rel_file = str(file_path)

            self.repo.index.add([rel_file])

            # Create commit with review note as the entire message
            commit = self.repo.index.commit(commit_message)
            return commit.hexsha[:8]

        except git.GitCommandError as e:
            msg = f"Failed to commit rule change: {e}"
            raise ValueError(msg) from e

    def commit_per_component(
        self,
        component_files: dict[str, list[Path]],
        component_notes: dict[str, str | None],
    ) -> dict[str, str]:
        """Create individual commits per component (validation, relationships, etc).

        Args:
            component_files: Map of component name to list of changed files
            component_notes: Map of component name to review note

        Returns:
            Map of component name to commit hash

        Raises:
            ValueError: If git operations fail

        """
        commits = {}

        try:
            for component, files in component_files.items():
                if not files:
                    continue

                # Check if there are changes in these files
                diff_index = self.repo.index.diff(None)
                has_changes = any(
                    str(Path(path)).startswith(str(f))
                    for d in diff_index
                    for f in files
                    if (path := d.a_path or d.b_path)
                    is not None  # Filter out None values
                )

                if not has_changes:
                    continue

                # Stage files for this component
                rel_files = []
                for file_path in files:
                    try:
                        rel_path = file_path.relative_to(self.repo.working_dir)
                        rel_files.append(str(rel_path))
                    except ValueError:
                        rel_files.append(str(file_path))

                self.repo.index.add(rel_files)

                # Generate commit message
                review_note = component_notes.get(component)
                commit_msg = self._generate_commit_message(
                    f"Update {component} from Excel import",
                    {component: review_note},
                )

                # Create commit
                commit = self.repo.index.commit(commit_msg)
                commits[component] = commit.hexsha[:8]

            return commits

        except git.GitCommandError as e:
            msg = f"Failed to commit changes: {e}"
            raise ValueError(msg) from e

    def _generate_commit_message(
        self,
        summary: str,
        review_notes: dict[str, str | None],
    ) -> str:
        """Generate commit message from summary and review notes.

        Args:
            summary: First line of commit message
            review_notes: Map of component/type to review note text

        Returns:
            Full commit message with review notes

        """
        lines = [summary]

        # Add review notes if present
        has_notes = any(v for v in review_notes.values())
        if has_notes:
            lines.append("")

            for note in review_notes.values():
                if note:
                    lines.append(f"Review Note: {note}")

        # Add import metadata
        lines.append("")
        lines.append("Source: Excel import")
        lines.append(f"Imported: {datetime.now(UTC).isoformat()}")

        return "\n".join(lines)
