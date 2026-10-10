#!/usr/bin/python3
"""Serve only the generated website on loopback; Ctrl+C stops this server."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path

from _bootstrap import ROOT
from tactile_kit.records import execution


class Handler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(404, "Directory listing disabled")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "build/site")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not (directory / "index.html").is_file():
        parser.error("Generated index.html not found; run scripts/reproduce.py first")
    if not 0 <= args.port <= 65535:
        parser.error("port must be in 0..65535")
    with execution(ROOT / "build/records", "Serve generated static website on loopback") as record:
        with ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(directory))) as server:
            record.update({"bind": "127.0.0.1", "port": server.server_port, "served_directory": str(directory)})
            print(f"Serving http://127.0.0.1:{server.server_port}/ · PID {os.getpid()}", flush=True)
            print("Ctrl+C in this terminal stops this server.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                record["intentional_stop_requests"].append("Ctrl+C for this owned HTTP server")


if __name__ == "__main__":
    main()
