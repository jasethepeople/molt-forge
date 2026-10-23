"""Agent identities: Ed25519 keypairs, one per agent role.

Identities live in a JSON store inside the JOB directory (never in the
evidence package — the package carries public keys only, in the manifest).
Because the keys live on disk with the job, an agent process can be killed
and a successor process picks up the SAME identity and continues the SAME
signed chain. That property is the demo: agents are disposable, the signed
history is not.

Demo-grade storage note: private keys sit in the job dir unencrypted. That
is acceptable for a hackathon workstation demo and is called out here rather
than hidden; production would seal them (cf. Jason-OS GHOST/SHADOW tiers).
"""

from __future__ import annotations

import json
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

ROLES = ("orchestrator", "planner", "fixer", "skeptic", "verifier")


class Identity:
    def __init__(self, name: str, private: Ed25519PrivateKey):
        self.name = name
        self._private = private
        self.pub_hex = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

    def sign_hex(self, message: bytes) -> str:
        return self._private.sign(message).hex()

    @staticmethod
    def verify_hex(pub_hex: str, sig_hex: str, message: bytes) -> bool:
        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
            pub.verify(bytes.fromhex(sig_hex), message)
            return True
        except Exception:
            return False


class IdentityStore:
    """Load-or-create the per-job identity set."""

    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        self._cache: dict[str, Identity] = {}

    def get(self, role: str) -> Identity:
        if role in self._cache:
            return self._cache[role]
        if role not in self._data:
            priv = Ed25519PrivateKey.generate()
            raw = priv.private_bytes(serialization.Encoding.Raw,
                                     serialization.PrivateFormat.Raw,
                                     serialization.NoEncryption())
            pub = priv.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self._data[role] = {"priv": raw.hex(), "pub": pub.hex()}
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self._data[role]["priv"]))
        ident = Identity(role, priv)
        self._cache[role] = ident
        return ident

    def public_keys(self) -> dict:
        return {role: self.get(role).pub_hex for role in list(self._data) or []}
