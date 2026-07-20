"""Check Claude-native replay events have stable identity and incremental replay."""
import json
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native import NativeSession  # noqa: E402


def _seqs(events):
    return [ev.get("seq") for ev in events]


def main():
    with tempfile.TemporaryDirectory() as td:
        ns = NativeSession("s-replay", ".", user="alice", state_dir=td)
        first = ns._record_event({"type": "user", "message": {"role": "user", "content": "hi"}})
        second = ns._record_event({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})

        assert first["seq"] == 1
        assert first["event_id"] == "s-replay:1"
        assert second["seq"] == 2
        assert second["event_id"] == "s-replay:2"

        full = ns.replay_payload()
        assert _seqs(full["events"]) == [1, 2]
        assert full["last_seq"] == 2
        assert full["snapshot"]["last_seq"] == 2

        inc = ns.replay_payload(after_seq=1)
        assert _seqs(inc["events"]) == [2]
        assert inc["last_seq"] == 2

        ns._busy = True
        ns.current_turn_started_at = 456.25
        ns._persist()
        saved = json.loads(Path(td, "native_s-replay.json").read_text(encoding="utf-8"))
        assert saved["next_seq"] == 3
        assert _seqs(saved["events"]) == [1, 2]
        assert saved["busy"] is True
        assert saved["current_turn_started_at"] == 456.25

        recovered = NativeSession.recover("s-replay", ".", user="alice", state_dir=td)
        assert recovered is not None
        assert _seqs(recovered.replay_payload()["events"]) == [1, 2]
        assert recovered._busy is True
        assert recovered.current_turn_started_at == 456.25
        third = recovered._record_event({"type": "result", "subtype": "success"})
        assert third["seq"] == 3
        assert third["event_id"] == "s-replay:3"

        legacy_path = Path(td, "native_legacy.json")
        legacy_path.write_text(json.dumps({
            "cwd": ".",
            "events": [
                {"type": "user", "message": {"content": "legacy"}},
                {"type": "assistant", "seq": 7, "event_id": "legacy-event"},
            ],
        }), encoding="utf-8")
        legacy = NativeSession.recover("legacy", ".", state_dir=td)
        assert legacy is not None
        replay = legacy.replay_payload()
        assert _seqs(replay["events"]) == [1, 7]
        assert replay["events"][0]["event_id"] == "legacy:1"
        assert replay["events"][1]["event_id"] == "legacy-event"
        assert legacy._record_event({"type": "result"})["seq"] == 8

    print("native replay identity checks passed")


if __name__ == "__main__":
    main()
