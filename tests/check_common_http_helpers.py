"""Check shared HTTP helpers after extraction."""
import io
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_http  # noqa: E402


def _handler(cls=common_http.BaseHandler):
    handler = object.__new__(cls)
    handler.request_version = "HTTP/1.1"
    handler.command = "GET"
    handler.requestline = "GET / HTTP/1.1"
    handler.client_address = ("127.0.0.1", 12345)
    handler.wfile = io.BytesIO()
    return handler


def main():
    assert common_http.ThreadingServer.daemon_threads is True
    assert common_http.ThreadingServer.allow_reuse_address is False
    assert common.BaseHandler.index_path == common.INDEX
    assert common.BaseHandler.static_root == common.ASSETS_DIR

    json_handler = _handler()
    json_handler._json({"ok": True})
    raw = json_handler.wfile.getvalue()
    assert b"HTTP/1.1 200 OK" in raw
    assert b"Content-Type: application/json; charset=utf-8" in raw
    assert raw.endswith(b'{"ok": true}')

    with tempfile.TemporaryDirectory() as td:
        index = Path(td, "index.html")
        index.write_text("<html>ok</html>", encoding="utf-8")

        class IndexHandler(common_http.BaseHandler):
            index_path = str(index)

        index_handler = _handler(IndexHandler)
        index_handler._serve_index()
        served = index_handler.wfile.getvalue()
        assert b"HTTP/1.1 200 OK" in served
        assert b"Cache-Control: no-store, no-cache, must-revalidate" in served
        assert served.endswith(b"<html>ok</html>")

        assets = Path(td, "assets")
        assets.mkdir()
        (assets / "app.js").write_text("console.log('ok');\n", encoding="utf-8", newline="\n")

        class StaticHandler(common_http.BaseHandler):
            static_root = str(assets)

        static_handler = _handler(StaticHandler)
        static_handler._serve_static("/assets/app.js")
        static_served = static_handler.wfile.getvalue()
        assert b"HTTP/1.1 200 OK" in static_served
        assert b"Content-Type: application/javascript; charset=utf-8" in static_served
        assert static_served.endswith(b"console.log('ok');\n")

        traversal_handler = _handler(StaticHandler)
        traversal_handler._serve_static("/assets/../index.html")
        assert b"HTTP/1.1 404 Not Found" in traversal_handler.wfile.getvalue()

    print("common http helper checks passed")


if __name__ == "__main__":
    main()
