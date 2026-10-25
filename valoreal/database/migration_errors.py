"""Errors raised by the migration command and by migration revisions.

Kept dependency-free so frozen revision files can import it safely.
"""


class MigrationError(RuntimeError):
    """A migration command cannot proceed; the message says what to do."""


class MigrationConflictError(MigrationError):
    """Existing rows violate constraints a revision is about to add.

    Raised before the revision changes anything; the whole upgrade rolls back.
    """

    def __init__(self, revision, conflicts):
        self.revision = revision
        self.conflicts = list(conflicts)
        details = "\n".join(f"  - {conflict}" for conflict in self.conflicts)
        super().__init__(
            f"Revision {revision} was not applied because existing data conflicts with "
            f"its constraints. Nothing was changed. Fix these rows, then run the "
            f"upgrade again:\n{details}"
        )


class SchemaVersionError(MigrationError):
    """The database schema does not match what this version of the code requires."""
