import uuid

import pytest

from app.core.auth import InvalidTokenError, create_access_token, decode_access_token, hash_secret, verify_secret


def test_hash_secret_roundtrip():
    hashed = hash_secret("correct horse battery staple")
    assert verify_secret("correct horse battery staple", hashed)
    assert not verify_secret("wrong password", hashed)


def test_hash_secret_never_stores_plaintext():
    hashed = hash_secret("my-otp-code-123456")
    assert "123456" not in hashed


def test_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_access_token_rejects_garbage():
    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")


def test_access_token_rejects_wrong_signature():
    import jwt

    forged = jwt.encode({"sub": str(uuid.uuid4())}, "wrong-secret-key", algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged)
