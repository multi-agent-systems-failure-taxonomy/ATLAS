"""Blocking localhost web view for explicit interactive taxonomy picking.

Serves:
  * GET /                       -> table: exactly 3 columns repo, taxonomy_id,
                                   domain; global across all repos; rows click
                                   through to detail. Plus a "use none" option.
  * GET /taxonomy/<id>          -> full content of one taxonomy (every code:
                                   number, name, explanation, and any extra
                                   fields).
  * GET /choose?id=<id|__none__> -> records the choice and ends the session.

run_webview() blocks until a choice is made, then returns the chosen
taxonomy_id, or "none".
"""

from __future__ import annotations

import html
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import store

NONE_SENTINEL = "__none__"  # query value meaning "start from 0"

# Fields rendered with dedicated emphasis in the detail view; any other field
# on a code is still shown generically ("all fields").
_CODE_PRIMARY = ("id", "name", "description", "category")

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 60rem;
         color: #1c2128; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
  th, td {{ text-align: left; padding: .55rem .75rem; border-bottom: 1px solid #d0d7de; }}
  th {{ background: #f6f8fa; font-size: .8rem; text-transform: uppercase;
        letter-spacing: .03em; color: #57606a; }}
  tr.row:hover {{ background: #f0f6ff; cursor: pointer; }}
  a {{ color: #0969da; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{ background: #eff1f3; padding: .1rem .35rem; border-radius: 4px; }}
  .none {{ display: inline-block; margin-top: 1.5rem; padding: .5rem .9rem;
           background: #1c2128; color: #fff; border-radius: 6px; }}
  .code-block {{ border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem;
                 margin: 1rem 0; }}
  .code-num {{ display: inline-block; min-width: 1.6rem; height: 1.6rem;
               line-height: 1.6rem; text-align: center; background: #0969da;
               color: #fff; border-radius: 50%; font-size: .85rem; }}
  .extra {{ color: #57606a; font-size: .9rem; margin-top: .4rem; }}
  .meta {{ color: #57606a; }}
</style></head><body>
{body}
</body></html>"""


def _render_table(store_dir) -> str:
    rows = []
    for rec in store.list_all(store_dir):
        tid = html.escape(str(rec["taxonomy_id"]))
        rows.append(
            '<tr class="row" onclick="location=\'/taxonomy/{tid}\'">'
            "<td>{repo}</td>"
            '<td><a href="/taxonomy/{tid}">{tid}</a></td>'
            "<td>{domain}</td></tr>".format(
                tid=tid,
                repo=html.escape(str(rec["repo"])),
                domain=html.escape(str(rec["domain"])),
            )
        )
    body = (
        "<h1>Inherit a taxonomy</h1>"
        "<p class='meta'>Pick a taxonomy to inherit, or start from 0. "
        "The table is global across all repos.</p>"
        "<table><thead><tr><th>repo</th><th>taxonomy_id</th><th>domain</th></tr>"
        "</thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<a class="none" href="/choose?id={none}">Use none / start from 0</a>'
    ).format(none=NONE_SENTINEL)
    return _PAGE.format(title="Inherit a taxonomy", body=body)


def _render_detail(taxonomy_id, store_dir) -> str:
    record = store.fetch_by_id(taxonomy_id, store_dir)
    tid = html.escape(str(record["taxonomy_id"]))
    blocks = []
    for code in record.get("codes", []):
        num = html.escape(str(code["id"]))
        name = html.escape(str(code["name"]))
        explanation = html.escape(str(code["description"]))
        extras = "".join(
            '<div class="extra"><b>{k}:</b> {v}</div>'.format(
                k=html.escape(str(k)), v=html.escape(str(v))
            )
            for k, v in code.items()
            if k not in _CODE_PRIMARY
        )
        blocks.append(
            '<div class="code-block">'
            '<div><span class="code-num">{num}</span> <b>{name}</b></div>'
            "<p>{explanation}</p>{extras}</div>".format(
                num=num, name=name, explanation=explanation, extras=extras
            )
        )
    body = (
        '<p><a href="/">&larr; back to all taxonomies</a></p>'
        "<h1>{tid}</h1>"
        '<p class="meta">repo <code>{repo}</code> &middot; '
        "domain <code>{domain}</code></p>"
        "{blocks}"
        '<a class="none" href="/choose?id={tid}">Inherit this taxonomy</a>'
    ).format(
        tid=tid,
        repo=html.escape(str(record.get("repo"))),
        domain=html.escape(str(record.get("domain"))),
        blocks="".join(blocks),
    )
    return _PAGE.format(title=tid, body=body)


def build_server(store_dir=store.DEFAULT_STORE_DIR, host="127.0.0.1", port=0):
    """Build (server, result, done) without starting it.

    `result` is a dict whose "value" is set to the chosen taxonomy_id or
    "none" once a choice is made; `done` is a threading.Event set at that
    point. Exposed separately so tests can drive the server directly.
    """
    result: dict = {"value": None}
    done = threading.Event()
    # Only ids actually in the store may be fetched -> no path traversal.
    valid_ids = {r["taxonomy_id"] for r in store.list_all(store_dir)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console quiet
            pass

        def _send(self, body, status=200, content_type="text/html; charset=utf-8"):
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/":
                self._send(_render_table(store_dir))
                return

            if path.startswith("/taxonomy/"):
                tid = path[len("/taxonomy/"):]
                if tid not in valid_ids:
                    self._send(
                        _PAGE.format(title="not found", body="<h1>404</h1>"
                                     "<p>No such taxonomy.</p>"
                                     '<p><a href="/">back</a></p>'),
                        status=404,
                    )
                    return
                self._send(_render_detail(tid, store_dir))
                return

            if path == "/choose":
                params = parse_qs(parsed.query)
                chosen = (params.get("id") or [""])[0]
                if chosen == NONE_SENTINEL:
                    result["value"] = "none"
                elif chosen in valid_ids:
                    result["value"] = chosen
                else:
                    self._send(
                        _PAGE.format(title="bad choice", body="<h1>400</h1>"
                                     "<p>Unknown choice.</p>"
                                     '<p><a href="/">back</a></p>'),
                        status=400,
                    )
                    return
                self._send(
                    _PAGE.format(
                        title="done",
                        body="<h1>Choice recorded</h1>"
                        "<p>Selected: <code>{}</code>.</p>"
                        "<p>You may close this tab and return to the terminal.</p>".format(
                            html.escape(result["value"])
                        ),
                    )
                )
                done.set()
                return

            self._send(_PAGE.format(title="not found", body="<h1>404</h1>"), status=404)

    server = HTTPServer((host, port), Handler)
    return server, result, done


def run_webview(store_dir=store.DEFAULT_STORE_DIR, host="127.0.0.1", port=0,
                open_browser=True, on_serving=None) -> str:
    """Launch the blocking web view; return the chosen taxonomy_id or "none".

    Blocks until the user makes a choice in the browser.
    `on_serving(host, port)` is invoked once the server is up (used by tests).
    """
    server, result, done = build_server(store_dir, host, port)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://{host}:{actual_port}/"
        if on_serving is not None:
            on_serving(host, actual_port)
        print(f"Taxonomy picker open at {url}  (waiting for your choice...)")
        if open_browser:
            webbrowser.open(url)
        done.wait()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    return result["value"]
