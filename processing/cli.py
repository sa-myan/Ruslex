"""Offline AI tools: inventory, prepare, run, report, build. Never writes live DB."""
import argparse
import json
from pathlib import Path
from .storage import inventory, prepare
from .workflow import run, report, build

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("inventory")
    check.add_argument("--db", required=True, type=Path)
    setup = sub.add_parser("prepare")
    setup.add_argument("--db", required=True, type=Path)
    setup.add_argument("--workspace", required=True, type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("--workspace", required=True, type=Path)
    execute.add_argument("--stage", required=True, choices=("lexemes", "pages"))
    execute.add_argument("--model", required=True, help="Exact provider/model ID from opencode models")
    execute.add_argument("--opencode-bin", default="opencode")
    execute.add_argument("--batch-size", type=int)
    execute.add_argument("--max-batches", type=int)
    execute.add_argument("--timeout", type=int, default=300)
    execute.add_argument("--verify-model", help="Optional second independent LLM verification pass")
    execute.add_argument("--dry-run", action="store_true")
    status = sub.add_parser("report")
    status.add_argument("--workspace", required=True, type=Path)
    assemble = sub.add_parser("build")
    assemble.add_argument("--workspace", required=True, type=Path)
    assemble.add_argument("--out", required=True, type=Path)
    assemble.add_argument("--allow-partial", action="store_true",
                          help="Only for previewing an incomplete enrichment, NOT production")
    args = parser.parse_args(argv)
    if args.command == "inventory":
        result = inventory(args.db)
    elif args.command == "prepare":
        result = prepare(args.db, args.workspace)
    elif args.command == "run":
        batch_size = args.batch_size or (4 if args.stage == "lexemes" else 2)
        if not 1 <= batch_size <= 8 or (args.max_batches is not None and args.max_batches < 1):
            parser.error("batch-size must be 1–8 and max-batches must be positive")
        result = run(args.workspace, stage=args.stage, model=args.model,
                     executable=args.opencode_bin, batch_size=batch_size,
                     max_batches=args.max_batches, timeout=args.timeout,
                     dry_run=args.dry_run, verify_model=args.verify_model)
    elif args.command == "report":
        result = report(args.workspace)
    else:
        result = build(args.workspace, args.out, allow_partial=args.allow_partial)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
