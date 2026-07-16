"""Static contract checks for native replay loading feedback in index.html."""
import subprocess
import sys
import tempfile
import os
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


class ScriptExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.parts.append(data)


def main():
    html = INDEX.read_text(encoding="utf-8")
    parser = ScriptExtractor()
    parser.feed(html)
    js = "\n".join(parser.parts)

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        js_path = f.name
    try:
        subprocess.run(["node", "--check", js_path], check=True)
    finally:
        try:
            os.unlink(js_path)
        except OSError:
            pass

    required = [
        "function nReplayRenderableEvents(events)",
        "function nStageHasReplayContent(st)",
        "function nReplayCommonPrefix(a,b)",
        "function nReplayProgressCancel(st)",
        "Connecting session",
        "Waiting for conversation replay",
        "No replay history",
        "if(!opts.silent) nReplayProgressStart",
        "_sig===st.lastReplayBatchSig && _hasContent",
        "st.replaySigParts=_parts",
        "nReplayBatchAsync(sid, st, _tail, {silent:true})",
        "_prefix===_oldParts.length",
        "if(st.replayWaiting && !st.replayActive)",
    ]
    missing = [token for token in required if token not in js]
    assert not missing, "missing replay loading contracts: %r" % missing
    print("ok")


if __name__ == "__main__":
    main()
