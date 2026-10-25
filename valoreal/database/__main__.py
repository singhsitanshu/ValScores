"""Create the canonical schema: ``python -m valoreal.database``."""

from .connection import initialize_database


if __name__ == "__main__":
    initialize_database()
