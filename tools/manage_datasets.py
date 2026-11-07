"""Import, clone and refresh standalone StarExplorer SQLite datasets."""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import datasets as D


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Generate a complete dataset from the source data")
    create.add_argument("destination", type=Path)
    create.add_argument("--data-dir", type=Path, default=ROOT / "data")
    create.add_argument("--name")
    create.add_argument("--seed", type=int)

    import_snapshot = commands.add_parser(
        "import-snapshot", help="Convert an existing full snapshot to the relational dataset format"
    )
    import_snapshot.add_argument("source", type=Path, help="Existing full scenario snapshot database")
    import_snapshot.add_argument("destination", type=Path)
    import_snapshot.add_argument("--stars", type=Path, default=ROOT / "data" / "stars.json")
    import_snapshot.add_argument("--name")

    clone = commands.add_parser("clone", help="Create a full independent copy of a dataset")
    clone.add_argument("source", type=Path)
    clone.add_argument("destination", type=Path)
    clone.add_argument("--name")

    refresh = commands.add_parser(
        "refresh", help="Recalculate stored flags after editing planetary rows directly with SQL"
    )
    refresh.add_argument("database", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "create":
            result = D.create_dataset(args.data_dir, args.destination, args.name, args.seed)
        elif args.command == "import-snapshot":
            result = D.import_legacy_snapshot(args.source, args.stars, args.destination, args.name)
        elif args.command == "clone":
            result = D.clone_dataset(args.source, args.destination, args.name)
        else:
            D.DatasetStore(args.database).refresh()
            result = args.database
        print(result)
    except (D.DatasetError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Dataset command failed: {exc}\n")


if __name__ == "__main__":
    main()
