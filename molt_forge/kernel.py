"""Hash-chained append-only event log.

Each event is one JSON line. Every event carries ``sha256(prev_hash + payload)``
so the chain is tamper-evident, resumable (re-open and continue appending) and
verifiable offline (``python -m molt_forge.kernel verify <log>``).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

GENESIS = "0" * 64


def canonical(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def event_hash(prev_hash: str, payload) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + canonical(payload)).hexdigest()


class EventLog:
    """Append-only, hash-chained, resumable event log (JSON Lines)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = []
        if self.path.exists():
            self._load()

    def _load(self):
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    self.events.append(json.loads(line))

    @property
    def last_hash(self) -> str:
        return self.events[-1]["hash"] if self.events else GENESIS

    @property
    def next_seq(self) -> int:
        return self.events[-1]["seq"] + 1 if self.events else 0

    def append(self, event_type: str, payload: dict, signer=None) -> dict:
        """Append an event. With ``signer`` (a signing.Identity), the event is
        attributed to that agent and carries an Ed25519 signature over the
        event hash, verifiable offline from the pub key stored in the event."""
        event = {
            "seq": self.next_seq,
            "ts": time.time(),
            "type": event_type,
            "payload": payload,
            "prev_hash": self.last_hash,
        }
        if signer is not None:
            event["actor"] = signer.name
        event["hash"] = event_hash(event["prev_hash"], {
            "seq": event["seq"], "ts": event["ts"],
            "type": event["type"], "payload": event["payload"],
            **({"actor": event["actor"]} if signer is not None else {}),
        })
        if signer is not None:
            event["pub"] = signer.pub_hex
            event["sig"] = signer.sign_hex(bytes.fromhex(event["hash"]))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
            fh.flush()
        self.events.append(event)
        return event

    @staticmethod
    def verify_file(path) -> tuple[bool, list[str]]:
        errors: list[str] = []
        prev = GENESIS
        expected_seq = 0
        p = Path(path)
        if not p.exists():
            return False, [f"log not found: {path}"]
        with p.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"line {lineno}: invalid JSON: {exc}")
                    continue
                if ev.get("seq") != expected_seq:
                    errors.append(f"line {lineno}: seq {ev.get('seq')} != expected {expected_seq}")
                if ev.get("prev_hash") != prev:
                    errors.append(f"line {lineno}: prev_hash mismatch (chain broken)")
                body = {"seq": ev.get("seq"), "ts": ev.get("ts"),
                        "type": ev.get("type"), "payload": ev.get("payload")}
                if ev.get("actor") is not None:
                    body["actor"] = ev["actor"]
                if event_hash(prev, body) != ev.get("hash"):
                    errors.append(f"line {lineno}: hash mismatch (payload tampered?)")
                if ev.get("sig") is not None:
                    from .signing import Identity
                    if not ev.get("pub") or not Identity.verify_hex(
                            ev["pub"], ev["sig"], bytes.fromhex(ev.get("hash", ""))):
                        errors.append(f"line {lineno}: BAD SIGNATURE (actor={ev.get('actor')})")
                prev = ev.get("hash", prev)
                expected_seq += 1
        return (not errors), errors


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "verify":
        ok, errors = EventLog.verify_file(argv[1])
        if ok:
            print(f"OK: {argv[1]} hash chain intact")
            return 0
        print(f"FAILED: {argv[1]}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("usage: python -m molt_forge.kernel verify <events.jsonl>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
