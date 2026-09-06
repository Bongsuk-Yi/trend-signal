#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데이터 암호화 / 복호화

GitHub Pages 는 공개 URL이므로 데이터 파일을 그냥 올리면 누구나 읽을 수 있다.
그래서 JSON을 gzip 압축 → AES-256-GCM 암호화 해서 올리고,
브라우저가 비밀번호로 복호화한다. 서버 없이도 실질적인 비밀번호 보호가 된다.

  키 유도 : PBKDF2-HMAC-SHA256, 310,000 iterations, 16-byte salt
  암호화  : AES-256-GCM, 12-byte IV, 16-byte tag
  (브라우저 Web Crypto API 와 완전히 호환되는 조합)

사용법:
  python scripts/crypt.py encrypt data/latest.json site/data/latest.enc.json
  python scripts/crypt.py decrypt site/data/latest.enc.json data/latest.json

비밀번호는 환경변수 SITE_PASSWORD 에서 읽는다.
"""

import base64
import gzip
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITERATIONS = 310_000
SALT_LEN = 16
IV_LEN = 12


def derive(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def ub64(s: str) -> bytes:
    return base64.b64decode(s)


def encrypt(src, dst, password):
    with open(src, "rb") as f:
        plain = f.read()

    packed = gzip.compress(plain, 9)
    salt = os.urandom(SALT_LEN)
    iv = os.urandom(IV_LEN)
    key = derive(password, salt)
    ct = AESGCM(key).encrypt(iv, packed, None)

    envelope = {
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iterations": ITERATIONS,
        "cipher": "AES-256-GCM",
        "compression": "gzip",
        "salt": b64(salt),
        "iv": b64(iv),
        "data": b64(ct),
    }

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(envelope, f, separators=(",", ":"))

    print(f"암호화 완료: {src} ({len(plain):,}B) → {dst} "
          f"({os.path.getsize(dst):,}B, 압축 후 {len(packed):,}B)")


def decrypt(src, dst, password):
    with open(src, encoding="utf-8") as f:
        env = json.load(f)

    key = derive(password, ub64(env["salt"]))
    packed = AESGCM(key).decrypt(ub64(env["iv"]), ub64(env["data"]), None)
    plain = gzip.decompress(packed) if env.get("compression") == "gzip" else packed

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as f:
        f.write(plain)
    print(f"복호화 완료: {src} → {dst} ({len(plain):,}B)")


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("encrypt", "decrypt"):
        print(__doc__)
        return 2

    password = os.environ.get("SITE_PASSWORD", "")
    if not password:
        print("오류: 환경변수 SITE_PASSWORD 가 비어 있습니다.", file=sys.stderr)
        return 1
    if len(password) < 8:
        print("오류: 비밀번호는 8자 이상이어야 합니다.", file=sys.stderr)
        return 1

    mode, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        (encrypt if mode == "encrypt" else decrypt)(src, dst, password)
    except Exception as e:  # noqa: BLE001
        print(f"{mode} 실패: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
