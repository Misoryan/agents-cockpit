# -*- coding: utf-8 -*-
"""Process, port, manager-spawn, and shutdown helpers."""
import http.client
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessSettings:
    picker_port: int
    manager_host: str
    manager_port: int
    run_mode: str
    base_dir: str
    create_no_window: int
    state_dir: str
    stop_sentinel: str
    expected_auth: str
    manager_path: str = ""


def is_local_client(addr):
    host = addr[0] if addr else ""
    return host in ("127.0.0.1", "::1", "localhost")


def lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def wait_port(port, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if port_alive(port):
            return True
        time.sleep(0.15)
    return False


def port_alive(port, timeout=0.5):
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout)
        sock.close()
        return True
    except OSError:
        return False


def kill_pid(pid, create_no_window=0):
    """Kill a process by PID; Windows uses taskkill /T for process trees."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           creationflags=create_no_window,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            import signal as _sig
            try:
                os.kill(pid, _sig.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                time.sleep(0.15)
            try:
                os.kill(pid, _sig.SIGKILL)
            except OSError:
                pass
    except Exception:
        pass


def pid_alive(pid):
    """True if a process with this pid currently exists."""
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, 0, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            kernel.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


_JOB_HANDLE = [None]


def bind_to_kill_on_close_job():
    """Windows only: bind current process to a kill-on-close Job Object."""
    if os.name != "nt":
        return False
    _JOB_HANDLE[0] = create_kill_on_close_job()
    return _JOB_HANDLE[0] is not None


def create_kill_on_close_job():
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE

        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            print("[job] CreateJobObject failed(err=%d); stop command remains cleanup fallback"
                  % ctypes.get_last_error())
            return None

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class _BASIC_LIMITS(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_void_p),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _EXT_LIMITS(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BASIC_LIMITS),
                        ("IoInfo", _IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = _EXT_LIMITS()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            print("[job] SetInformationJobObject failed(err=%d); stop command remains cleanup fallback"
                  % ctypes.get_last_error())
            return None
        if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
            print("[job] AssignProcessToJobObject failed(err=%d); stop command remains cleanup fallback"
                  % ctypes.get_last_error())
            return None
        return handle
    except Exception as exc:
        print("[job] Job Object setup failed(%s); stop command remains cleanup fallback" % exc)
        return None


def manager_path(settings):
    return settings.manager_path or (sys.argv[0] if sys.argv and sys.argv[0] else __file__)


def manager_argv(settings):
    return [sys.executable, os.path.abspath(manager_path(settings)), "--manager"]


def manager_available(settings):
    try:
        conn = http.client.HTTPConnection(settings.manager_host, settings.manager_port, timeout=0.8)
        conn.request("GET", "/api/backends")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return 200 <= resp.status < 500
    except OSError:
        return False


def ensure_manager(settings, is_stopping=lambda: False):
    if is_stopping():
        return False
    if settings.run_mode == "manager" or manager_available(settings):
        return True
    popen_kwargs = {
        "cwd": settings.base_dir,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = settings.create_no_window
    subprocess.Popen(manager_argv(settings), **popen_kwargs)
    deadline = time.time() + 8
    while time.time() < deadline:
        if manager_available(settings):
            return True
        time.sleep(0.2)
    return False


def http_post(port, path, auth=""):
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("POST", path, body=b"{}",
                     headers={"Authorization": auth, "Content-Type": "application/json"})
        conn.getresponse().read()
        conn.close()
        return True
    except OSError:
        return False


def write_stop_sentinel(settings):
    try:
        os.makedirs(settings.state_dir, exist_ok=True)
        with open(os.path.join(settings.state_dir, settings.stop_sentinel), "w") as f:
            f.write("stop\n")
    except OSError:
        pass


def perform_shutdown(settings, kill_registry_sessions):
    web_ok = http_post(settings.picker_port, "/api/_stop", settings.expected_auth)
    if not web_ok:
        write_stop_sentinel(settings)
    http_post(settings.manager_port, "/api/_exit", settings.expected_auth)
    kill_registry_sessions()
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if not port_alive(settings.picker_port) and not port_alive(settings.manager_port):
            break
        time.sleep(0.25)
    sup_pid_path = os.path.join(settings.state_dir, "supervisor.pid")
    try:
        with open(sup_pid_path, "r") as f:
            sup_pid = int((f.read() or "0").strip())
        if sup_pid:
            kill_pid(sup_pid, settings.create_no_window)
    except (OSError, ValueError):
        pass
    try:
        os.unlink(sup_pid_path)
    except OSError:
        pass
    return {
        "web_port_free": not port_alive(settings.picker_port),
        "manager_port_free": not port_alive(settings.manager_port),
    }
