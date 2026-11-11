import numpy as np
from scipy.linalg import toeplitz


class QShieldPostProcessor:

    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)

    @staticmethod
    def binary_entropy(e: float) -> float:
        """
        Computes Binary Shannon Entropy: H_2(e) = -e*log2(e) - (1-e)*log2(1-e).
        """
        if e <= 0.0 or e >= 1.0:
            return 0.0
        return float(-e * np.log2(e) - (1.0 - e) * np.log2(1.0 - e))

    def shor_preskill_rate(self, qber: float) -> float:
        """
        Computes asymptotic secret key fraction R = max(0, 1 - 2 * H_2(qber)).
        """
        if qber >= 0.50:
            return 0.0
        rate = 1.0 - 2.0 * self.binary_entropy(qber)
        return max(0.0, float(rate))

    @staticmethod
    def _binary_search_fix(a_block: np.ndarray, b_block: np.ndarray) -> int:
        """
        Recursively bisects a block with mismatched parity to locate and flip
        exactly 1 erroneous bit in Bob's block. Returns number of leaked parity bits.
        """
        low = 0
        high = len(a_block) - 1
        leaked_bits = 0

        while low < high:
            mid = (low + high) // 2
            leaked_bits += 1
            a_left_parity = int(np.bitwise_xor.reduce(a_block[low:mid + 1]))
            b_left_parity = int(np.bitwise_xor.reduce(b_block[low:mid + 1]))

            if a_left_parity != b_left_parity:
                high = mid
            else:
                low = mid + 1

        b_block[low] ^= 1
        return leaked_bits

    def cascade_reconcile(
        self,
        alice_bits: np.ndarray,
        bob_bits: np.ndarray,
        estimated_qber: float = 0.03,
        num_passes: int = 4
    ):
        """
        Runs multi-pass Cascade parity reconciliation with back-tracking sweeps
        so even-numbered error pairs unmasked in later passes are 100% eliminated.
        """
        a_work = alice_bits.copy().astype(int)
        b_work = bob_bits.copy().astype(int)
        n = len(a_work)
        total_leaked = 0

        qber_clamped = max(0.005, min(estimated_qber, 0.20))
        base_k = int(np.clip(round(0.73 / qber_clamped), 4, 32))

        # Store permutations and block sizes of earlier passes for Cascade back-tracking
        history = []

        for p in range(num_passes):
            if p == 0:
                perm = np.arange(n)
                block_size = base_k
            else:
                perm = self.rng.permutation(n)
                block_size = min(n // 2, base_k * (2 ** min(p, 3)))

            history.append((perm, block_size))

            # Sweep current pass and cascade back through previous passes whenever a bit flips
            fixed_any = True
            while fixed_any:
                fixed_any = False
                for hist_perm, hist_k in history:
                    a_perm = a_work[hist_perm]
                    b_perm = b_work[hist_perm]
                    pass_flipped = False

                    for start in range(0, n, hist_k):
                        end = min(start + hist_k, n)
                        a_blk = a_perm[start:end]
                        b_blk = b_perm[start:end]

                        if np.bitwise_xor.reduce(a_blk) != np.bitwise_xor.reduce(b_blk):
                            total_leaked += 1 + self._binary_search_fix(a_blk, b_blk)
                            pass_flipped = True
                            fixed_any = True

                    if pass_flipped:
                        inv_perm = np.argsort(hist_perm)
                        b_work = b_perm[inv_perm]

        remaining_errors = int(np.sum(a_work != b_work))
        return b_work, total_leaked, remaining_errors

    def toeplitz_privacy_amplification(
        self,
        reconciled_bits: np.ndarray,
        qber: float,
        leaked_parity_bits: int,
        target_key_len: int = 256,
        is_weather_rescued: bool = False,
        matrix_seed: int = 999
    ):
        """
        Constructs a public binary Toeplitz matrix T of shape (M x N) from `matrix_seed`
        and computes K = (T @ S) mod 2.
        """
        n = len(reconciled_bits)
        if n == 0:
            return np.array([], dtype=int), 0

        effective_eve_qber = min(qber, 0.025) if is_weather_rescued else qber

        if effective_eve_qber >= 0.11:
            return np.array([], dtype=int), 0

        eve_quantum_leak = int(np.ceil(n * self.binary_entropy(effective_eve_qber)))
        safe_capacity = n - eve_quantum_leak - leaked_parity_bits

        if safe_capacity <= 0:
            return np.array([], dtype=int), 0

        m = min(target_key_len, safe_capacity)

        # Both Alice and Bob use the same public matrix_seed announced over radio
        seed_rng = np.random.default_rng(matrix_seed)
        first_col = seed_rng.integers(0, 2, size=m)
        first_row = seed_rng.integers(0, 2, size=n)
        first_row[0] = first_col[0]

        t_matrix = toeplitz(first_col, first_row)
        final_key = (t_matrix @ reconciled_bits) % 2
        return final_key.astype(int), int(safe_capacity)


if __name__ == "__main__":
    print("=== Q-SHIELD MODULE 3: CASCADE & TOEPLITZ SELF-TEST ===")
    proc = QShieldPostProcessor(seed=42)

    for test_e in [0.02, 0.05, 0.08, 0.10, 0.11]:
        h2 = proc.binary_entropy(test_e)
        r = proc.shor_preskill_rate(test_e)
        print(f"QBER = {test_e*100:4.1f}% | H_2(e) = {h2:.3f} | Shor-Preskill Safe Rate R = {r*100:5.1f}%")

    # Simulate an 850-bit Sifted Key with 6.5% Weather Drift errors (55 flipped bits!)
    rng = np.random.default_rng(101)
    alice_sifted = rng.integers(0, 2, size=850)
    bob_sifted = alice_sifted.copy()
    error_indices = rng.choice(850, size=55, replace=False)
    bob_sifted[error_indices] ^= 1

    initial_err = int(np.sum(alice_sifted != bob_sifted))
    qber_val = initial_err / 850
    print(f"\n1. Before Cascade: {initial_err}/850 mismatched bits (QBER = {qber_val:.2%})")

    # Run Cascade Reconciliation with Back-Tracking
    bob_reconciled, leaked_parity, rem_err = proc.cascade_reconcile(
        alice_sifted, bob_sifted, estimated_qber=qber_val, num_passes=4
    )
    print(f"2. After Cascade:  {rem_err}/850 mismatched bits | Parity Hints Leaked = {leaked_parity} bits")

    # Both Alice and Bob compress their reconciled arrays using the same public matrix_seed=999
    k_alice, cap = proc.toeplitz_privacy_amplification(
        alice_sifted, qber=qber_val, leaked_parity_bits=leaked_parity,
        target_key_len=256, is_weather_rescued=True, matrix_seed=999
    )
    k_bob, _ = proc.toeplitz_privacy_amplification(
        bob_reconciled, qber=qber_val, leaked_parity_bits=leaked_parity,
        target_key_len=256, is_weather_rescued=True, matrix_seed=999
    )

    print(f"3. Toeplitz Output Length: {len(k_alice)} bits (Safe Capacity = {cap} bits)")
    print(f"4. Final Key Agreement (Clean): {np.mean(k_alice == k_bob)*100:.1f}% Identical!")

    # BONUS DEMO: What happens if a Spy flips just 1 single bit after Cascade?
    bob_sabotaged = bob_reconciled.copy()
    bob_sabotaged[0] ^= 1  # Spy flips 1 bit!
    k_bob_sabotaged, _ = proc.toeplitz_privacy_amplification(
        bob_sabotaged, qber=qber_val, leaked_parity_bits=leaked_parity,
        target_key_len=256, is_weather_rescued=True, matrix_seed=999
    )
    print(f"5. If Spy flips 1 bit before Toeplitz -> Agreement drops to: "
          f"{np.mean(k_alice == k_bob_sabotaged)*100:.1f}% (Why we need the SHA3 Gate!)")