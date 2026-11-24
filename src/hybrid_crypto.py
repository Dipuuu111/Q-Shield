import os
import hmac
import hashlib
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ModuleLWE_KEM:
    Q = 3329
    N = 256
    HALF_Q = 1665

    def __init__(self, parameter_set: str = "ML-KEM-768", seed: int = None):
        self.k = 4 if parameter_set == "ML-KEM-1024" else 3
        self.eta = 2
        self.parameter_set = parameter_set
        self.rng = np.random.default_rng(seed)

    @classmethod
    def _poly_mul_mod(cls, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        # Negacyclic wrap-around for mod (X^256 + 1): terms >= X^256 wrap with a minus sign
        full_conv = np.convolve(a.astype(np.int64), b.astype(np.int64))
        low = full_conv[:cls.N]
        high = np.zeros(cls.N, dtype=np.int64)
        high[:len(full_conv) - cls.N] = full_conv[cls.N:]
        return (low - high) % cls.Q

    def _cbd_noise(self, shape) -> np.ndarray:
        a = self.rng.integers(0, 2, size=(*shape, self.eta)).sum(axis=-1)
        b = self.rng.integers(0, 2, size=(*shape, self.eta)).sum(axis=-1)
        return a - b

    def keygen(self):
        A = self.rng.integers(0, self.Q, size=(self.k, self.k, self.N))
        s = self._cbd_noise((self.k, self.N))
        e = self._cbd_noise((self.k, self.N))

        t = np.zeros((self.k, self.N), dtype=np.int64)
        for i in range(self.k):
            for j in range(self.k):
                t[i] = (t[i] + self._poly_mul_mod(A[i, j], s[j])) % self.Q
            t[i] = (t[i] + e[i]) % self.Q

        return (A, t), s

    def encaps(self, public_key):
        A, t = public_key
        m_bits = self.rng.integers(0, 2, size=self.N, dtype=int)

        r = self._cbd_noise((self.k, self.N))
        e1 = self._cbd_noise((self.k, self.N))
        e2 = self._cbd_noise((self.N,))

        u = np.zeros((self.k, self.N), dtype=np.int64)
        for i in range(self.k):
            for j in range(self.k):
                u[i] = (u[i] + self._poly_mul_mod(A[j, i], r[j])) % self.Q
            u[i] = (u[i] + e1[i]) % self.Q

        v = np.zeros(self.N, dtype=np.int64)
        for j in range(self.k):
            v = (v + self._poly_mul_mod(t[j], r[j])) % self.Q
        v = (v + e2 + self.HALF_Q * m_bits) % self.Q

        shared_secret = hashlib.sha3_256(np.packbits(m_bits).tobytes()).digest()
        return (u, v), shared_secret

    def decaps(self, ciphertext, secret_key) -> bytes:
        u, v = ciphertext
        s = secret_key

        s_dot_u = np.zeros(self.N, dtype=np.int64)
        for j in range(self.k):
            s_dot_u = (s_dot_u + self._poly_mul_mod(s[j], u[j])) % self.Q

        w = (v - s_dot_u) % self.Q
        # Values within Q/4 of HALF_Q decode to 1; otherwise 0
        dist_to_center = np.abs(w - self.HALF_Q)
        recovered_bits = (dist_to_center < (self.Q // 4)).astype(np.uint8)

        return hashlib.sha3_256(np.packbits(recovered_bits).tobytes()).digest()


class QShieldHybridCrypto:
    @staticmethod
    def bits_to_bytes(bit_array: np.ndarray) -> bytes:
        if len(bit_array) == 0:
            return b""
        return np.packbits(bit_array.astype(np.uint8)).tobytes()

    @classmethod
    def verify_qkd_integrity(cls, k_hq_bits: np.ndarray, k_border_bits: np.ndarray):
        if len(k_hq_bits) < 256 or len(k_border_bits) < 256:
            return False, "EMPTY_KEY", "EMPTY_KEY"

        hq_hash = hashlib.sha3_256(cls.bits_to_bytes(k_hq_bits[:256])).hexdigest()
        border_hash = hashlib.sha3_256(cls.bits_to_bytes(k_border_bits[:256])).hexdigest()

        is_synced = hmac.compare_digest(hq_hash, border_hash)
        return is_synced, hq_hash, border_hash

    @staticmethod
    def hkdf_sha3_256(
        ikm: bytes,
        salt: bytes = b"QSHIELD-SALT-2026",
        info: bytes = b"Q-SHIELD-FIPS203-HYBRID"
    ) -> bytes:
        prk = hmac.new(salt, ikm, hashlib.sha3_256).digest()
        okm = hmac.new(prk, info + b"\x01", hashlib.sha3_256).digest()
        return okm

    def establish_hybrid_master_key(
        self,
        k_hq_bits: np.ndarray,
        k_border_bits: np.ndarray,
        ai_class: int = 0
    ):
        sha3_ok, hq_digest, border_digest = self.verify_qkd_integrity(k_hq_bits, k_border_bits)

        use_qkd = (ai_class in [0, 1]) and sha3_ok
        kem_level = "ML-KEM-768" if use_qkd else "ML-KEM-1024"

        kem = ModuleLWE_KEM(parameter_set=kem_level)
        pk, sk = kem.keygen()
        ct, kem_secret_bob = kem.encaps(pk)
        kem_secret_alice = kem.decaps(ct, sk)
        assert kem_secret_alice == kem_secret_bob, "ML-KEM Decapsulation Mismatch!"

        if use_qkd:
            qkd_bytes = self.bits_to_bytes(k_border_bits[:256])
            ikm = qkd_bytes + kem_secret_bob
            mode_status = f"HYBRID_ACTIVE (QKD-256 + {kem_level})"
        else:
            ikm = kem_secret_bob
            reason = "SHA3_SABOTAGE_CAUGHT" if not sha3_ok else f"AI_QUARANTINE_CLASS_{ai_class}"
            mode_status = f"PQC_FAILOVER_ONLY ({kem_level} | Reason: {reason})"

        k_master = self.hkdf_sha3_256(ikm)

        return {
            "k_master": k_master,
            "mode_status": mode_status,
            "kem_level": kem_level,
            "sha3_verified": sha3_ok,
            "hq_sha3_hex": hq_digest[:16] + "...",
            "border_sha3_hex": border_digest[:16] + "...",
        }

    @staticmethod
    def encrypt_tactical_message(k_master: bytes, plaintext: str) -> dict:
        aesgcm = AESGCM(k_master)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=b"Q-SHIELD-BORDER-AUTH")
        return {
            "nonce_hex": nonce.hex(),
            "ciphertext_hex": ciphertext.hex(),
            "raw_nonce": nonce,
            "raw_ciphertext": ciphertext,
        }

    @staticmethod
    def decrypt_tactical_message(k_master: bytes, nonce: bytes, ciphertext: bytes) -> str:
        aesgcm = AESGCM(k_master)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, associated_data=b"Q-SHIELD-BORDER-AUTH")
        return decrypted_bytes.decode("utf-8")


if __name__ == "__main__":
    print("=== Q-SHIELD MODULE 4: SHA3 GATE, ML-KEM & AES-256-GCM SELF-TEST ===")
    crypto = QShieldHybridCrypto()
    rng = np.random.default_rng(7)

    k_alice = rng.integers(0, 2, size=256)
    k_bob_clean = k_alice.copy()

    res_clean = crypto.establish_hybrid_master_key(k_alice, k_bob_clean, ai_class=1)
    print("\n[TEST 1: Weather-Rescued Link]")
    print("  SHA3-256 Sync: ", res_clean["sha3_verified"],
          f"({res_clean['hq_sha3_hex']} == {res_clean['border_sha3_hex']})")
    print("  Mode Status:   ", res_clean["mode_status"])
    print("  K_Master Hex:  ", res_clean["k_master"].hex()[:32] + "...")

    msg = "SECTOR-4 RADAR ALERT: PATROL UNIT ALPHA PROCEED TO GRID 78-N"
    enc_packet = crypto.encrypt_tactical_message(res_clean["k_master"], msg)
    dec_msg = crypto.decrypt_tactical_message(
        res_clean["k_master"], enc_packet["raw_nonce"], enc_packet["raw_ciphertext"]
    )
    print("  AES-256-GCM Ciphertext:", enc_packet["ciphertext_hex"][:40] + "...")
    print("  Decrypted Command:     ", dec_msg)

    k_bob_poisoned = k_alice.copy()
    k_bob_poisoned[:128] ^= 1

    res_sabotage = crypto.establish_hybrid_master_key(k_alice, k_bob_poisoned, ai_class=0)
    print("\n[TEST 2: Spy Sabotage Caught by SHA3 Gate!]")
    print("  SHA3-256 Sync: ", res_sabotage["sha3_verified"],
          f"({res_sabotage['hq_sha3_hex']} != {res_sabotage['border_sha3_hex']})")
    print("  Mode Status:   ", res_sabotage["mode_status"])
    print("  K_Master Hex:  ", res_sabotage["k_master"].hex()[:32] + "...")
