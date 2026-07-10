"""Web-view tests: drive the real HTTP server, no browser needed."""

import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from finding import webview

STORE_DIR = Path(__file__).resolve().parent / "fixtures" / "taxonomies"


class WebViewTests(unittest.TestCase):
    def setUp(self):
        self.server, self.result, self.done = webview.build_server(STORE_DIR)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def _get(self, path):
        with urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            return resp.read().decode("utf-8")

    def test_table_has_three_columns_and_is_global(self):
        body = self._get("/")
        for header in ("repo", "taxonomy_id", "domain"):
            self.assertIn(f"<th>{header}</th>", body)
        # global across repos: rows from more than one repo present
        self.assertIn("django/django", body)
        self.assertIn("numpy/numpy", body)

    def test_detail_shows_full_content(self):
        body = self._get("/taxonomy/tax-numpy-array-003")
        self.assertIn("View vs copy aliasing mutation", body)      # name
        self.assertIn("broadcast", body.lower())                   # explanation
        self.assertIn("b = a[::2]", body)                          # extra field

    def test_choose_id_records_choice_and_finishes(self):
        self._get("/choose?id=tax-flask-routing-004")
        self.assertTrue(self.done.wait(timeout=2))
        self.assertEqual(self.result["value"], "tax-flask-routing-004")

    def test_choose_none_path(self):
        self._get(f"/choose?id={webview.NONE_SENTINEL}")
        self.assertTrue(self.done.wait(timeout=2))
        self.assertEqual(self.result["value"], "none")


class RenderTableBraceRegressionTests(unittest.TestCase):
    def test_braces_in_repo_and_domain_do_not_crash_table(self):
        # Regression: repo/domain carrying `{`/`}` used to blow up the picker
        # index because `.format` ran over the already-interpolated rows.
        import tempfile

        from finding import store

        store_dir = Path(tempfile.mkdtemp())
        store.register(
            {
                "taxonomy_id": "t-braces",
                "repo": "acme/{svc}",
                "domain": "web {SPA}",
                "codes": [
                    {"id": "A.1", "name": "n", "description": "d", "category": "A"}
                ],
            },
            store_dir,
        )
        html = webview._render_table(store_dir)
        self.assertIn("acme/{svc}", html)
        self.assertIn("web {SPA}", html)


if __name__ == "__main__":
    unittest.main()
