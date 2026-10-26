"""Create immutable full-population snapshots and publish editable scenarios."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scenarios as C


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Freeze all systems, including all moons")
    snapshot.add_argument("id")
    snapshot.add_argument("--name")
    snapshot.add_argument("--seed", type=int)
    create = commands.add_parser("create", help="Create and publish an empty baseline overlay")
    create.add_argument("id")
    create.add_argument("--baseline", required=True)
    create.add_argument("--name")
    export = commands.add_parser("export", help="Export one complete editable system replacement")
    export.add_argument("id")
    export.add_argument("system", help="Catalogue name, renamed display name or stable star ID")
    export.add_argument("--output", type=Path)
    publish = commands.add_parser("publish", help="Validate overrides and publish a new immutable revision")
    publish.add_argument("id")
    default = commands.add_parser("set-default")
    default.add_argument("id")
    purge = commands.add_parser("purge", help="Remove all obsolete SQLite revisions (stop the app first)")
    purge.add_argument("--dry-run", action="store_true", help="List obsolete revisions without deleting them")
    commands.add_parser("list")
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            result = C.snapshot(args.data_dir, args.id, args.name, args.seed)
        elif args.command == "create":
            result = C.create_scenario(args.data_dir, args.id, args.baseline, args.name)
        elif args.command == "export":
            print(C.export_system(args.data_dir, args.id, args.system, args.output))
            return
        elif args.command == "publish":
            result = C.publish(args.data_dir, args.id)
        elif args.command == "set-default":
            C.set_default(args.data_dir, args.id)
            print(f"Default scenario: {args.id}")
            return
        elif args.command == "purge":
            result = C.purge(args.data_dir, dry_run=args.dry_run)
        else:
            result = C.Store(args.data_dir, C.read_json(args.data_dir / "stars.json")["stars"]).list()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (C.ScenarioError, OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Scenario command failed: {exc}\n")


if __name__ == "__main__":
    main()
