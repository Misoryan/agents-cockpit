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
        self.srcs = []
        self.current_external = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            attrs = dict(attrs)
            src = attrs.get("src") or ""
            self.current_external = bool(src)
            if src:
                self.srcs.append(src)
            self.in_script = True

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self.in_script = False
            self.current_external = False

    def handle_data(self, data):
        if self.in_script and not self.current_external:
            self.parts.append(data)


def _local_script_text(src):
    if src.startswith(("http://", "https://", "//")):
        return ""
    src_path = src.split("?", 1)[0].lstrip("/")
    path = ROOT / src_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main():
    html = INDEX.read_text(encoding="utf-8")
    assert 'href="/assets/app.css"' in html
    assert 'id="lm-args"' not in html
    assert 'id="set-args"' not in html
    parser = ScriptExtractor()
    parser.feed(html)
    js = "\n".join(parser.parts + [_local_script_text(src) for src in parser.srcs])
    local_scripts = [src for src in parser.srcs if src.startswith("/assets/")]
    assert local_scripts == [
        "/assets/app_core.js",
        "/assets/app_sidebar.js",
        "/assets/app_state.js",
        "/assets/native_utils.js",
        "/assets/native_stage.js",
        "/assets/native_replay.js",
        "/assets/native_forms.js",
        "/assets/native_events.js",
        "/assets/native_socket.js",
        "/assets/native_actions.js",
        "/assets/app_launch.js",
        "/assets/app_usage_settings.js",
        "/assets/app_init.js",
        "/assets/auth.js",
        "/assets/icons.js",
    ]

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
        "function nReplayUnseenEvents(st, events)",
        "function nReplayProgressCancel(st)",
        "/api/history?limit=200&live_codex=1",
        "function nativeScheduleReconnect(sid, delay)",
        "function nativeReconnectDelay(sid, baseDelay)",
        "if(existing && (existing.readyState===0 || existing.readyState===1) && !opts.force) return existing",
        "if(nativeReconnectTimers[sid]) return",
        "function nativeStartPolling(sid, immediate)",
        "\"/api/nreplay?sid=\"+encodeURIComponent(sid)+\"&after=\"+encodeURIComponent(after)",
        "\"?after=\"+encodeURIComponent(String(after))",
        "\"retry=\"+nativeReconnectDelay(sid,1500)+\"ms\"",
        "Connecting session",
        "Waiting for conversation replay",
        "No replay history",
        "if(!opts.silent) nReplayProgressStart",
        "_sig===st.lastReplayBatchSig && _hasContent",
        "if(_hasContent){",
        "var _unseen=nReplayUnseenEvents(st,_evs)",
        "st.replaySigParts=_parts",
        "nReplayBatchAsync(sid, st, _unseen, {silent:true})",
        "window.NATIVE_DEBUG",
        "if(st.replayWaiting && !st.replayActive)",
    ]
    missing = [token for token in required if token not in js]
    assert not missing, "missing replay loading contracts: %r" % missing
    print("ok")


if __name__ == "__main__":
    main()
