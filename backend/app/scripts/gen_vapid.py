"""Generate a fresh VAPID keypair for Web Push.

Usage:
    cd backend && .venv/bin/python -m app.scripts.gen_vapid

Prints `VAPID_PUBLIC_KEY=` and `VAPID_PRIVATE_KEY=` lines — paste them into
`backend/.env`.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid01 as Vapid


def main() -> None:
    v = Vapid()
    v.generate_keys()
    pub_raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()
    priv_int = v.private_key.private_numbers().private_value
    priv_bytes = priv_int.to_bytes(32, "big")
    priv_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode()
    print(f"VAPID_PUBLIC_KEY={pub_b64}")
    print(f"VAPID_PRIVATE_KEY={priv_b64}")
    print("VAPID_SUBJECT=mailto:admin@example.com")


if __name__ == "__main__":
    main()
