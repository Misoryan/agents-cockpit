"""Check process/manager helpers after extracting them from common.py."""
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_process  # noqa: E402


class FakeResponse:
    status = 204

    def read(self):
        return b""


class FakeConnection:
    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(self, method, path, body=None, headers=None):
        self.requested = (method, path, body, headers)

    def getresponse(self):
        return FakeResponse()

    def close(self):
        pass


def _free_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def main():
    assert common_process.is_local_client(("127.0.0.1", 1))
    assert common_process.is_local_client(("::1", 1))
    assert not common_process.is_local_client(("192.0.2.1", 1))
    assert common._is_local_client(("127.0.0.1", 1))

    sock, port = _free_listener()
    stop_accept = [False]
    def accept_loop():
        sock.settimeout(0.1)
        while not stop_accept[0]:
            try:
                conn, _addr = sock.accept()
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                break
    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    try:
        assert common_process.port_alive(port)
        assert common_process.wait_port(port, timeout=0.2)
    finally:
        stop_accept[0] = True
        sock.close()

    with tempfile.TemporaryDirectory() as td:
        settings = common_process.ProcessSettings(
            picker_port=1111,
            manager_host="127.0.0.1",
            manager_port=2222,
            run_mode="manager",
            base_dir=td,
            create_no_window=0,
            state_dir=td,
            stop_sentinel="stop.sentinel",
            expected_auth="Basic test",
            manager_path="app.py",
        )
        assert common_process.manager_argv(settings)[-2:] == [os.path.abspath("app.py"), "--manager"]
        assert common_process.ensure_manager(settings) is True
        stopped_settings = common_process.ProcessSettings(**{**settings.__dict__, "run_mode": "web"})
        assert common_process.ensure_manager(stopped_settings, is_stopping=lambda: True) is False

        old_conn = common_process.http.client.HTTPConnection
        try:
            common_process.http.client.HTTPConnection = FakeConnection
            assert common_process.manager_available(stopped_settings)
        finally:
            common_process.http.client.HTTPConnection = old_conn

        common_process.write_stop_sentinel(settings)
        assert Path(td, "stop.sentinel").read_text(encoding="utf-8") == "stop\n"

        old_http_post = common_process.http_post
        old_port_alive = common_process.port_alive
        old_kill_pid = common_process.kill_pid
        calls = []
        killed = []
        try:
            common_process.http_post = lambda port, path, auth="": calls.append((port, path, auth)) or path != "/api/_stop"
            common_process.port_alive = lambda _port, timeout=0.5: False
            common_process.kill_pid = lambda pid, create_no_window=0: killed.append(pid)
            Path(td, "supervisor.pid").write_text("12345", encoding="utf-8")
            report = common_process.perform_shutdown(settings, lambda: calls.append(("registry", "", "")))
            assert (1111, "/api/_stop", "Basic test") in calls
            assert (2222, "/api/_exit", "Basic test") in calls
            assert ("registry", "", "") in calls
            assert killed == [12345]
            assert report == {"web_port_free": True, "manager_port_free": True}
        finally:
            common_process.http_post = old_http_post
            common_process.port_alive = old_port_alive
            common_process.kill_pid = old_kill_pid

    print("common process helper checks passed")


if __name__ == "__main__":
    main()
