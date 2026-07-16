"""Check Codex input, file mention, and image helper behavior."""
import base64
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_input  # noqa: E402


class FakeClient:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.ensured = False

    def ensure(self):
        self.ensured = True

    def request(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        if method == "fuzzyFileSearch":
            return {"files": [
                {"root": self.root, "path": "README.md", "file_name": "README.md", "score": 99},
                {"root": self.root, "path": "..\\outside.txt", "file_name": "outside.txt", "score": 100},
            ]}
        return {}


class FakeSession:
    def __init__(self, root):
        self.sid = "s-input"
        self.cwd = os.path.abspath(root)
        self.state_dir = os.path.join(root, "state")
        self.user = ""
        self.client = FakeClient(self.cwd)

    def _client(self):
        return self.client


def assert_raises_message(fn, text):
    try:
        fn()
    except ValueError as exc:
        assert text in str(exc)
        return
    raise AssertionError("expected ValueError containing %r" % text)


def main():
    with tempfile.TemporaryDirectory() as td:
        Path(td, "README.md").write_text("# hello\n", encoding="utf-8")
        adapter = codex_input.CodexInputAdapter(FakeSession(td))

        assert adapter.path_within_cwd(Path(td, "README.md"))
        assert not adapter.path_within_cwd(Path(td).parent / "outside.txt")
        assert adapter.resolve_mention_path("README.md") == os.path.abspath(Path(td, "README.md"))
        assert adapter.resolve_mention_path("../outside.txt") == ""

        items = adapter.user_input_items('read @README.md and @"README.md"')
        mentions = [item for item in items if item.get("type") == "mention"]
        assert len(mentions) == 1
        assert mentions[0]["name"] == "README.md"

        images = adapter.prepare_image_inputs([{
            "name": "screen.png",
            "type": "image/png",
            "detail": "not-valid",
            "data_url": "data:image/png;base64,%s" % base64.b64encode(b"png").decode("ascii"),
        }])
        assert len(images) == 1
        assert images[0]["detail"] == "auto"
        assert images[0]["mime"] == "image/png"
        assert os.path.isfile(images[0]["path"])
        assert adapter.image_file(images[0]["image_id"]) == images[0]["path"]
        assert adapter.image_file("../" + images[0]["image_id"]) == images[0]["path"]
        assert adapter.image_file("missing.png") == ""

        image_items = adapter.user_input_items("", image_inputs=images)
        assert image_items == [{"type": "localImage", "path": images[0]["path"], "detail": "auto"}]
        display = adapter.display_user_content("look", image_inputs=images)
        assert display[0] == {"type": "text", "text": "look"}
        assert display[1]["image_id"] == images[0]["image_id"]

        assert_raises_message(lambda: adapter.prepare_image_inputs({"data": "AA=="}), "images must be an array")
        assert_raises_message(lambda: adapter.prepare_image_inputs([{"type": "text/plain", "data": "AA=="}]),
                              "unsupported image type")
        assert_raises_message(lambda: adapter.prepare_image_inputs([{"type": "image/png", "data": "not-b64"}]),
                              "invalid base64")

        files = adapter.search_files("readme", limit=10)["files"]
        assert files == [{
            "path": os.path.abspath(Path(td, "README.md")),
            "insert": "README.md",
            "name": "README.md",
            "match_type": "file",
            "score": 99,
        }]
        assert adapter.session.client.ensured
        assert adapter.session.client.calls == [("fuzzyFileSearch", {"query": "readme", "roots": [os.path.abspath(td)]}, 15)]

    print("codex input helper checks passed")


if __name__ == "__main__":
    main()
