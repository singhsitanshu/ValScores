"""Schema management: ``python -m valoreal.database {upgrade,baseline,status}``.

See docs/DATABASE.md for when to use each command.
"""

import argparse
import logging
import sys


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m valoreal.database",
        description="Manage the ValScores PostgreSQL schema (DATABASE_URL).",
    )
    parser.add_argument(
        "--env-file",
        help="load variables such as DATABASE_URL from this file first (existing "
             "environment variables win)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "upgrade",
        help="apply pending migrations; creates the schema in an empty database",
    )
    commands.add_parser(
        "baseline",
        help="verify a pre-Alembic database and mark it as revision 0001",
    )
    commands.add_parser(
        "status",
        help="show current and required revisions; exit 1 unless current",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    # Show each applied revision, without Alembic's connection chatter.
    migration_log = logging.getLogger("alembic.runtime.migration")
    migration_log.setLevel(logging.INFO)
    migration_log.addFilter(lambda record: record.getMessage().startswith("Running "))

    # Imported after --env-file: the connection module reads DATABASE_URL on import.
    from .migration_errors import MigrationError

    try:
        from .connection import engine
        from . import migrator

        if args.command == "upgrade":
            before, after = migrator.upgrade(engine)
            if before == after:
                print(f"Schema already at revision {after}; nothing to do.")
            else:
                print(f"Upgraded schema from {before or 'empty'} to {after}.")
        elif args.command == "baseline":
            print(migrator.baseline(engine))
        else:
            state = migrator.schema_state(engine)
            print(f"current revision: {state.current or 'none'}")
            print(f"required revision: {state.head}")
            try:
                migrator.ensure_schema_current(engine)
            except MigrationError as exc:
                print(exc)
                return 1
            print("Schema is current.")
    except (MigrationError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
