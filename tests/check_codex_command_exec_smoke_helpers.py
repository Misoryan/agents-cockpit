"""Static/helper checks for the live Codex command/exec smoke."""
import base64
import importlib.util
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "codex_command_exec_smoke.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("codex_command_exec_smoke", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    tool = _load_tool()
    src = inspect.getsource(tool)
    required = [
        '"command/exec"',
        '"command/exec/write"',
        '"command/exec/terminate"',
        "streamStdin",
        "streamStdoutStderr",
        "add_command_exec_output_handler",
        "remove_command_exec_output_handler",
    ]
    missing = [token for token in required if token not in src]
    assert not missing, "command exec smoke missing expected contracts: %r" % missing
    payload = base64.b64encode("hello".encode("utf-8")).decode("ascii")
    assert tool._decode_delta({"deltaBase64": payload}) == "hello"
    assert tool._b64("hello") == payload
    print("codex command exec smoke helper checks passed")


if __name__ == "__main__":
    main()
