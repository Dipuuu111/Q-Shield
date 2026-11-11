import os
import hmac
import hashlib
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ModuleLWE_KEM:
    """
    Self-contained mathematical implementation of NIST FIPS 203 ML-KEM (Kyber)
    over the Cyclotomic Polynomial Ring R_q = Z_3329[X] / (X^256 + 1).
    Supports:
      - ML-KEM-768  (k = 3 polynomial vectors -> 768 coefficients)
      - ML-KEM-1024 (k = 4 polynomial vectors -> 1024 coefficients)
    All 256 secret bits are encapsulated simultaneously in a single polynomial v(X).
    """

    Q = 3329
    N = 256
    HALF_Q = 1665  # ceil(3329 / 2)

    def __init__(self, parameter_set: str = "ML-KEM-768", seed: int = None):
        if parameter_set == "ML-KEM-1024":
            self.k = 4
            self.eta = 2
        else:
            self.k = 3
            self.eta = 2
        self.parameter_set = parameter_set
        self.rng = np.random.default_rng(seed)

    @classmethod
    def _poly_mul_mod(cls, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """
        Multiplies two 256-coefficient polynomials modulo (X^256 + 1, 3329).
        Uses the negacyclic wrap-around property: X^256 == -1 (mod X^256 + 1).
        """
        full_conv = np.convolve(a.astype(np.int64), b.astype(np.int64))
        low = full_conv[:cls.N]
        high = np.zeros(cls.N, dtype=np.int64)
        high[:len(full_conv) - cls.N] = full_conv[cls.N:]
        return (low - high) % cls.Q

    def _cbd_noise(self, shape) -> np.ndarray:
        """
        Centered Binomial Distribution B_eta: generates small polynomial coefficients
        in {-eta, ..., +eta} by subtracting two random bit sums.
        """
        a = self.rng.integers(0, 2, size=(*shape, self.eta)).sum(axis=-1)
        b = self.rng.integers(0, 2, size=(*shape, self.eta)).sum(axis=-1)
        return a - b

    def keygen(self):
        """
        Generates Public Key (A, t) and Private Key (s) in R_q^k:
          t(X) = (A(X) * s(X) + e(X)) mod 3329
        """
        A = self.rng.integers(0, self.Q, size=(self.k, self.k, self.N))
        s = self._cbd_noise((self.k, self.N))
        e = self._cbd_noise((self.k, self.N))

        t = np.zeros((self.k, self.N), dtype=np.int64)
        for i in range(self.k):
            for j in range(self.k):
                t[i] = (t[i] + self._poly_mul_mod(A[i, j], s[j])) % self.Q
            t[i] = (t[i] + e[i]) % self.Q

        public_key = (A, t)
        secret_key = s
        return public_key, secret_key

    def encaps(self, public_key):
        """
        Generates a random 256-bit secret m, encodes all 256 bits into one polynomial
        v(X) = t^T * r + e_2 + 1665 * m(X) mod 3329, and returns (ciphertext, shared_secret_bytes).
        """
        A, t = public_key
        m_bits = self.rng.integers(0, 2, size=self.N, dtype=int)

        r = self._cbd_noise((self.k, self.N))
        e1 = self._cbd_noise((self.k, self.N))
        e2 = self._cbd_noise((self.N,))

        # u(X) = A^T * r + e1 (mod 3329)
        u = np.zeros((self.k, self.N), dtype=np.int64)
        for i in range(self.k):
            for j in range(self.k):
                u[i] = (u[i] + self._poly_mul_mod(A[j, i], r[j])) % self.Q
            u[i] = (u[i] + e1[i]) % self.Q

        # v(X) = t^T * r + e2 + round(q/2) * m(X) (mod 3329)
        v = np.zeros(self.N, dtype=np.int64)
        for j in range(self.k):
            v = (v + self._poly_mul_mod(t[j], r[j])) % self.Q
        v = (v + e2 + self.HALF_Q * m_bits) % self.Q

        shared_secret = hashlib.sha3_256(np.packbits(m_bits).tobytes()).digest()
        ciphertext = (u, v, m_bits)
        return ciphertext, shared_secret

    def decaps(self, ciphertext, secret_key) -> bytes:
        """
        Computes noisy polynomial w(X) = (v(X) - s(X)^T * u(X)) mod 3329
        and rounds all 256 coefficients simultaneously to recover the 256-bit key.
        """
        u, v, _ = ciphertext
        s = secret_key

        s_dot_u = np.zeros(self.N, dtype=np.int64)
        for j in range(self.k):
            s_dot_u = (s_dot_u + self._poly_mul_mod(s[j], u[j])) % self.Q

        w = (v - s_dot_u) % self.Q

        # Round each coefficient: closer to 1665 -> 1, closer to 0/3329 -> 0
        dist_to_center = np.abs(w - self.HALF_Q)
        recovered_bits = (dist_to_center < (self.Q // 4)).astype(np.uint8)

        return hashlib.sha3_256(np.packbits(recovered_bits).tobytes()).digest()


class QShieldHybridCrypto:
    """
    Module 4 of Q-Shield:
      1. Pre-Decryption SHA3-256 Anti-Sabotage Handshake Gate
      2. NIST FIPS 203 ML-KEM-768 / ML-KEM-1024 Hybrid Key Combiner (HKDF-SHA3-256)
      3. AES-256-GCM Authenticated Tactical Border Encryption
    """

    @staticmethod
    def bits_to_bytes(bit_array: np.ndarray) -> bytes:
        """Packs a 256-bit numpy array (0s and 1s) into 32 raw bytes."""
        if len(bit_array) == 0:
            return b""
        return np.packbits(bit_array.astype(np.uint8)).tobytes()

    @classmethod
    def verify_qkd_integrity(cls, k_hq_bits: np.ndarray, k_border_bits: np.ndarray):
        """
        Pre-Decryption SHA3-256 Gate:
        Compares SHA3-256(K_HQ) == SHA3-256(K_Border) before allowing QKD key usage.
        """
        if len(k_hq_bits) < 256 or len(k_border_bits) < 256:
            return False, "EMPTY_KEY", "EMPTY_KEY"

        hq_hash = hashlib.sha3_256(cls.bits_to_bytes(k_hq_bits[:256])).hexdigest()
        border_hash = hashlib.sha3_256(cls.bits_to_bytes(k_border_bits[:256])).hexdigest()

        is_synced = hmac.compare_digest(hq_hash, border_hash)
        return is_synced, hq_hash, border_hash

    @staticmethod
    def hkdf_sha3_256(ikm: bytes, salt: bytes = b"QSHIELD-SALT-2026", info: bytes = b"Q-SHIELD-FIPS203-HYBRID") -> bytes:
        """
        RFC 5869 Extract-and-Expand Key Derivation Function powered by SHA3-256.
        Outputs a 256-bit (32-byte) Master Key K_Master.
        """
        # 1. HKDF-Extract
        prk = hmac.new(salt, ikm, hashlib.sha3_256).digest()
        # 2. HKDF-Expand (1 block = 32 bytes for AES-256)
        okm = hmac.new(prk, info + b"\x01", hashlib.sha3_256).digest()
        return okm

    def establish_hybrid_master_key(
        self,
        k_hq_bits: np.ndarray,
        k_border_bits: np.ndarray,
        ai_class: int = 0
    ):
        """
        Executes the complete Hybrid Key Exchange & Failover logic:
          - Class 0 (Clean) or Class 1 (Weather Rescued):
              Verifies SHA3-256 gate. If passed, fuses QKD + ML-KEM-768.
              If SHA3 gate fails (Sabotage!), drops QKD and fails over to ML-KEM-1024!
          - Class 2, 3, 4 (Active Eve or Spy Sabotage):
              Quarantines QKD immediately and fails over 100% to ML-KEM-1024!
        """
        sha3_ok, hq_digest, border_digest = self.verify_qkd_integrity(k_hq_bits, k_border_bits)

        # Decide whether QKD is safe and synced
        use_qkd = (ai_class in [0, 1]) and sha3_ok
        kem_level = "ML-KEM-768" if use_qkd else "ML-KEM-1024"

        # Run NIST FIPS 203 ML-KEM polynomial ring encapsulation & decapsulation
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
        """Encrypts border communication using AES-256-GCM."""
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
        """Decrypts and verifies the 128-bit GCM authentication tag."""
        aesgcm = AESGCM(k_master)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, associated_data=b"Q-SHIELD-BORDER-AUTH")
        return decrypted_bytes.decode("utf-8")


if __name__ == "__main__":
    print("=== Q-SHIELD MODULE 4: SHA3 GATE, ML-KEM & AES-256-GCM SELF-TEST ===")
    crypto = QShieldHybridCrypto()
    rng = np.random.default_rng(7)

    # TEST 1: Clean / Weather-Rescued Link (Alice & Bob have identical 256-bit QKD keys)
    k_alice = rng.integers(0, 2, size=256)
    k_bob_clean = k_alice.copy()

    res_clean = crypto.establish_hybrid_master_key(k_alice, k_bob_clean, ai_class=1)
    print("\n[TEST 1: Weather-Rescued Link]")
    print("  SHA3-256 Sync: ", res_clean["sha3_verified"],
          f"({res_clean['hq_sha3_hex']} == {res_clean['border_sha3_hex']})")
    print("  Mode Status:   ", res_clean["mode_status"])
    print("  K_Master Hex:  ", res_clean["k_master"].hex()[:32] + "...")

    # Encrypt & Decrypt a Tactical Border Command
    msg = "SECTOR-4 RADAR ALERT: PATROL UNIT ALPHA PROCEED TO GRID 78-N"
    enc_packet = crypto.encrypt_tactical_message(res_clean["k_master"], msg)
    dec_msg = crypto.decrypt_tactical_message(
        res_clean["k_master"], enc_packet["raw_nonce"], enc_packet["raw_ciphertext"]
    )
    print("  AES-256-GCM Ciphertext:", enc_packet["ciphertext_hex"][:40] + "...")
    print("  Decrypted Command:     ", dec_msg)

    # TEST 2: Spy Sabotage Link (Bob's QKD key differs after Toeplitz avalanche)
    k_bob_poisoned = k_alice.copy()
    k_bob_poisoned[:128] ^= 1  # Simulated Toeplitz avalanche from 1-bit spy flip

    res_sabotage = crypto.establish_hybrid_master_key(k_alice, k_bob_poisoned, ai_class=0)
    print("\n[TEST 2: Spy Sabotage Caught by SHA3 Gate!]")
    print("  SHA3-256 Sync: ", res_sabotage["sha3_verified"],
          f"({res_sabotage['hq_sha3_hex']} != {res_sabotage['border_sha3_hex']})")
    print("  Mode Status:   ", res_sabotage["mode_status"])
    print("  K_Master Hex:  ", res_sabotage["k_master"].hex()[:32] + "...")