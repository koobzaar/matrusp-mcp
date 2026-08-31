"""Entrypoint `matrusp-mcp` para servidor, coleta e validação."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .crawler.crawler import FetchPolicy, JupiterCrawler
from .http_server import create_http_app
from .mcp_server import create_server, run_stdio
from .snapshot import (
    build_snapshot,
    enforce_count_delta,
    load_previous_cache,
    publish_artifacts,
    validate_snapshot,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="matrusp-mcp", description="MatrUSP MCP read-only")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="serve MCP over stdio or Streamable HTTP")
    serve.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve.add_argument(
        "--snapshot",
        type=Path,
        default=Path(os.environ.get("MATRUSP_SNAPSHOT", "data/matrusp.sqlite")),
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    crawl = subparsers.add_parser("crawl", help="collect JupiterWeb and publish a snapshot")
    crawl.add_argument("--output", type=Path, required=True)
    crawl.add_argument("--previous", type=Path)
    crawl.add_argument("--concurrency", type=int, default=8)
    crawl.add_argument("--accept-large-delta", action="store_true")
    crawl.add_argument(
        "--artifacts",
        type=Path,
        help="also emit gzip snapshot, manifest and SHA256SUMS in this directory",
    )
    validate = subparsers.add_parser("validate", help="validate a local snapshot")
    validate.add_argument("snapshot", type=Path)
    return parser


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.environ.get(name, "").split(",") if value.strip())


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        report = validate_snapshot(args.snapshot)
        print(
            json.dumps(
                {"ok": report.ok, "counts": report.counts, "errors": report.errors},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if report.ok else 1
    if args.command == "serve":
        if args.transport == "stdio":
            asyncio.run(run_stdio(create_server(args.snapshot)))
            return 0
        import uvicorn

        uvicorn.run(
            create_http_app(
                args.snapshot,
                allowed_hosts=_csv_env("MATRUSP_ALLOWED_HOSTS"),
                allowed_origins=_csv_env("MATRUSP_ALLOWED_ORIGINS"),
            ),
            host=args.host,
            port=args.port,
            access_log=False,
        )
        return 0
    if args.command == "crawl":
        if args.accept_large_delta:
            # The flag is recorded by the release workflow; the crawler itself remains deterministic.
            pass
        previous_versions: dict[tuple[str, str], dict[str, object]] = {}
        previous_history = {}
        if args.previous is not None:
            cache = load_previous_cache(args.previous)
            previous_versions = cache.versions
            previous_history = cache.offering_history
        crawler = JupiterCrawler(
            policy=FetchPolicy(concurrency=args.concurrency),
            previous_versions=previous_versions,
            previous_history=previous_history,
        )
        data = asyncio.run(crawler.crawl())
        if args.previous is None:
            build_snapshot(data, args.output)
        else:
            candidate = args.output.with_name(f".{args.output.name}.candidate")
            try:
                build_snapshot(data, candidate)
                enforce_count_delta(args.previous, candidate, accept_large=args.accept_large_delta)
                os.replace(candidate, args.output)
            finally:
                candidate.unlink(missing_ok=True)
        artifacts = publish_artifacts(args.output, args.artifacts) if args.artifacts else None
        print(
            json.dumps(
                {
                    "snapshot_id": data.metadata.snapshot_id,
                    "output": str(args.output),
                    "artifacts": {key: str(value) for key, value in artifacts.items()}
                    if artifacts
                    else None,
                },
                sort_keys=True,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
