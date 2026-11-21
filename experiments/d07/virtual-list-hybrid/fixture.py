#!/usr/bin/env python3
"""Local virtual-list fixture for the hybrid adapter prototype.

The fixture intentionally replaces the rows on every scroll instead of
appending them, so the final DOM contains only the last batch. The adapter must
capture each batch before the next replacement.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOTAL_ITEMS = 12
BATCH_SIZE = 3


def virtual_list_html(total: int = TOTAL_ITEMS, batch_size: int = BATCH_SIZE) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Virtual list fixture</title>
<style>
  body {{ font-family: sans-serif; margin: 20px; }}
  #feed {{ height: 220px; overflow: auto; border: 1px solid #888; padding: 8px; }}
  .product {{ display: block; height: 32px; line-height: 32px; }}
  #spacer {{ height: 900px; }}
</style></head>
<body>
<h1>Virtual list fixture</h1>
<p id="status"></p>
<div id="feed">
  <div id="rows"></div>
  <div id="spacer"></div>
</div>
<script>
const total = {total};
const batchSize = {batch_size};
let start = 0;
const rows = document.getElementById('rows');
const feed = document.getElementById('feed');
const status = document.getElementById('status');

function render() {{
  const end = Math.min(start + batchSize, total);
  rows.innerHTML = '';
  for (let index = start; index < end; index += 1) {{
    const number = index + 1;
    const link = document.createElement('a');
    link.className = 'product';
    link.dataset.id = 'p' + number;
    link.href = '/product/p' + number + '.html';
    link.textContent = 'Product ' + number;
    rows.appendChild(link);
  }}
  status.textContent = 'rows ' + (start + 1) + '-' + end + ' of ' + total;
}}

feed.addEventListener('scroll', function () {{
  if (feed.scrollTop + feed.clientHeight < feed.scrollHeight - 10) {{ return; }}
  if (start + batchSize >= total) {{ return; }}
  start += batchSize;
  render();
  feed.scrollTop = 0;
}});

render();
</script>
</body></html>
"""


def product_html(index: int) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Product {index}</title></head>
<body><h1>Product {index}</h1></body></html>
"""


@contextmanager
def fixture_server() -> Iterator[str]:
    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request: Any, client_address: Any) -> None:
            import sys

            if isinstance(sys.exc_info()[1], ConnectionResetError):
                return
            super().handle_error(request, client_address)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/virtual.html":
                body = virtual_list_html().encode("utf-8")
            elif self.path.startswith("/product/p") and self.path.endswith(".html"):
                try:
                    index = int(self.path[len("/product/p") : -len(".html")])
                except ValueError:
                    index = 1
                body = product_html(index).encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = QuietServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    with fixture_server() as base:
        print(f"fixture: {base}/virtual.html", flush=True)
        input("press Enter to stop\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
