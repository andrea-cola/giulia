from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def generate_key_pair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def private_key_to_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def public_key_to_pem(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_private_key(pem_data: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem_data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("Key is not Ed25519")
    return key


def load_public_key(pem_data: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem_data)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("Key is not Ed25519")
    return key


def load_private_key_from_file(path_or_pem: str) -> Ed25519PrivateKey:
    """Load a private key from a file path or inline PEM string."""
    if path_or_pem.strip().startswith("-----"):
        return load_private_key(path_or_pem.encode())
    with open(path_or_pem, "rb") as f:
        return load_private_key(f.read())


def sign_payload(private_key: Ed25519PrivateKey, payload: dict[str, Any]) -> str:
    """Sign a JSON-serializable payload, return base64-encoded signature."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = private_key.sign(canonical)
    return base64.b64encode(sig).decode()


def verify_signature(
    public_key: Ed25519PublicKey, payload: dict[str, Any], signature_b64: str
) -> bool:
    """Verify a base64-encoded Ed25519 signature over a JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = base64.b64decode(signature_b64)
    try:
        public_key.verify(sig, canonical)
        return True
    except Exception:
        return False


def generate_did_key(public_key: Ed25519PublicKey) -> str:
    """Generate a did:key identifier from an Ed25519 public key."""
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    # multicodec prefix 0xed01 for Ed25519
    multicodec = b"\xed\x01" + raw
    encoded = base64.urlsafe_b64encode(multicodec).decode().rstrip("=")
    return f"did:key:z{encoded}"


def generate_did_web(domain: str, path: str = "") -> str:
    """Generate a did:web identifier from a domain and optional path."""
    did = f"did:web:{domain.replace(':', '%3A').replace('/', ':')}"
    if path:
        did += f":{path.replace('/', ':')}"
    return did


def create_vc_proof(
    private_key: Ed25519PrivateKey,
    did: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    """Create a W3C Verifiable Credential proof block."""
    sig = sign_payload(private_key, document)
    return {
        "type": "Ed25519Signature2020",
        "created": datetime.now(UTC).isoformat(),
        "verificationMethod": f"{did}#key-1",
        "proofPurpose": "assertionMethod",
        "proofValue": sig,
    }


def verify_vc_proof(
    public_key: Ed25519PublicKey,
    document: dict[str, Any],
    proof: dict[str, Any],
) -> bool:
    """Verify a VC proof against the document."""
    return verify_signature(public_key, document, proof.get("proofValue", ""))


def public_key_from_jwk(jwk: dict[str, str]) -> Ed25519PublicKey:
    """Load an Ed25519 public key from a JWK (RFC 8037) dict."""
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise ValueError(f"Unsupported JWK: kty={jwk.get('kty')}, crv={jwk.get('crv')}")
    x = jwk["x"]
    padding = 4 - len(x) % 4
    if padding != 4:
        x += "=" * padding
    raw = base64.urlsafe_b64decode(x)
    return Ed25519PublicKey.from_public_bytes(raw)


def public_key_to_jwk(
    public_key: Ed25519PublicKey, kid: str = "key-1"
) -> dict[str, str]:
    """Convert an Ed25519 public key to JWK (RFC 7517 / RFC 8037) format."""
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    x = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": x,
        "kid": kid,
        "use": "sig",
        "alg": "EdDSA",
    }


def sign_agent_card(
    private_key: Ed25519PrivateKey,
    card: dict[str, Any],
    kid: str = "key-1",
) -> dict[str, Any]:
    """Sign an A2A agent card and return it with a ``signatures`` array.

    Uses JSON Canonicalization (RFC 8785 — sorted keys, no whitespace)
    and produces a JWS Compact Serialization with an EdDSA signature.
    The ``signatures`` field is excluded from the signed payload.
    """
    card_without_sig = {k: v for k, v in card.items() if k != "signatures"}
    canonical = json.dumps(
        card_without_sig, sort_keys=True, separators=(",", ":")
    ).encode()

    header = {"alg": "EdDSA", "kid": kid}
    header_b64 = (
        base64.urlsafe_b64encode(
            json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    payload_b64 = base64.urlsafe_b64encode(canonical).decode().rstrip("=")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    raw_sig = private_key.sign(signing_input)
    sig_b64 = base64.urlsafe_b64encode(raw_sig).decode().rstrip("=")

    jws = f"{header_b64}.{payload_b64}.{sig_b64}"

    signed_card = dict(card_without_sig)
    signed_card["signatures"] = [jws]
    return signed_card


def check_vc_status_list(status_list_url: str, index: int) -> bool:
    """
    Check if a credential at `index` in a VC-Status-List is revoked.
    Returns True if the credential is still valid (not revoked).
    Placeholder -- real implementation would fetch the status list bitstring.
    """
    # TODO: implement actual HTTP fetch + bitstring check
    return True
