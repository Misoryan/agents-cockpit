# -*- coding: utf-8 -*-
"""Shared HTTP handler and threaded server classes."""
import http.server
import json
import mimetypes
import os
import socketserver
import urllib.parse


class BaseHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agent-cockpit/1.0"
    index_path = ""
    static_root = ""
    static_url_prefix = "/assets/"

    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_index(self):
        try:
            data = open(self.index_path, "rb").read()
        except OSError as exc:
            self._json({"error": str(exc)}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path):
        if not self.static_root or not path.startswith(self.static_url_prefix):
            self._json({"error": "not found"}, 404)
            return
        rel = urllib.parse.unquote(path[len(self.static_url_prefix):])
        rel = rel.replace("\\", "/").lstrip("/")
        root = os.path.abspath(self.static_root)
        target = os.path.abspath(os.path.join(root, rel))
        if target != root and not target.startswith(root + os.sep):
            self._json({"error": "not found"}, 404)
            return
        if not os.path.isfile(target):
            self._json({"error": "not found"}, 404)
            return
        try:
            data = open(target, "rb").read()
        except OSError as exc:
            self._json({"error": str(exc)}, 500)
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if target.endswith(".js"):
            ctype = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False
