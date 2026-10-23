"""Launch on demand from any compatible MCP client; never bind a socket."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fedleave import __version__


def main():
    parser = argparse.ArgumentParser(description="FedLeave MCP server (local stdio)")
    parser.add_argument("--version", action="version", version=f"fedleave-mcp {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=os.environ.get("FEDLEAVE_MCP_CONFIG"),
        help="Trusted administrator JSON policy file; never set by tools",
    )
    parser.add_argument("--inventory", action="store_true", help="Print the strict CLI parity inventory and exit")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")
    from .catalog import inventory
    from .policy import Policy
    from .server import serve

    try:
        if args.inventory:
            report = inventory()
            unknown = [t["tool"] for t in report["tools"] if t["classification"]["kind"] == "unclassified"]
            if unknown:
                raise ValueError(f"Unclassified CLI commands: {unknown}")
            print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
            return
        policy = Policy.load(args.config)
        asyncio.run(serve(policy, args.config))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.error("FedLeave MCP startup failed: %s", exc)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
