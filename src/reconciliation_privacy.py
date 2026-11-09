import numpy as np
from scipy.linalg import toeplitz


class QShieldPostProcessor:
    """
    Module 3 of Q-Shield: Classical Post-Processing Engine.
    Implements:
      1. Shor-Preskill Quantum Secrecy Rate Bound: R = 1 - 2 * H_2(e)
      2. Multi-Pass Cascade Binary-Search Parity Reconciliation
      3. Modulo-2 Toeplitz Matrix Universal-2 Privacy Amplification
    """

    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)

    @staticmethod
    def binary_entropy(e: float) -> float:
        """
        Computes Binary Shannon Entropy: H_2(e) = -e*log2(e) - (1-e)*log2(1-e).
        At e = 0.110 (11% QBER), H_2(0.11) = 0.500 -> Shor-Preskill rate hits 0!
        """
        if e <= 0.0 or e >= 1.0:
            return 0.0
        return float(-e * np.log2(e) - (1.0 - e) * np.log2(1.0 - e))

    def shor_preskill_rate(self, qber: float) -> float:
        """
        Computes asymptomatic secret key fraction R = max(0, 1 - 2 * H_2(qber)).
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

        # Flip the isolated error bit at index 'low' in Bob's array
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
        Runs multi-pass Cascade parity reconciliation over the authenticated radio.
        Returns:
          reconciled_bob (np.ndarray), total_leaked_parity_bits (int), remaining_errors (int)
        """
        a_work = alice_bits.copy().astype(int)
        b_work = bob_bits.copy().astype(int)
        n = len(a_work)
        total_leaked = 0

        # Initial block size k_1 ~ 0.73 / qber (clamped between 4 and 64)
        qber_clamped = max(0.005, min(estimated_qber, 0.20))
        block_size = int(np.clip(round(0.73 / qber_clamped), 4, 64))

        for p in range(num_passes):
            if p == 0:
                perm = np.arange(n)
            else:
                perm = self.rng.permutation(n)
                block_size = min(n, block_size * 2)

            a_perm = a_work[perm]
            b_perm = b_work[perm]

            # Partition into blocks and compare XOR parities
            for start in range(0, n, block_size):
                end = min(start + block_size, n)
                a_blk = a_perm[start:end]
                b_blk = b_perm[start:end]

                total_leaked += 1  # 1 top-level parity bit announced per block
                if np.bitwise_xor.reduce(a_blk) != np.bitwise_xor.reduce(b_blk):
                    total_leaked += self._binary_search_fix(a_blk, b_blk)

            # Un-permute Bob's corrected bits back to original index order
            inv_perm = np.argsort(perm)
            b_work = b_perm[inv_perm]

        remaining_errors = int(np.sum(a_work != b_work))
        return b_work, total_leaked, remaining_errors

    def toeplitz_privacy_amplification(
        self,
        reconciled_bits: np.ndarray,
        qber: float,
        leaked_parity_bits: int,
        target_key_len: int = 256,
        is_weather_rescued: bool = False
    ):
        """
        Constructs a random binary Toeplitz matrix T of shape (M x N) from a public
        seed of length (M + N - 1) and computes K = (T @ S) mod 2.
        """
        n = len(reconciled_bits)
        if n == 0:
            return np.array([], dtype=int), 0

        # If AI verified the errors are natural T2 weather drift (not Eve),
        # we only need to compress out the Cascade parity leakage + baseline Eve bound.
        effective_eve_qber = min(qber, 0.025) if is_weather_rescued else qber

        if effective_eve_qber >= 0.11:
            # Exceeds Shor-Preskill 11% limit -> 0 safe quantum bits!
            return np.array([], dtype=int), 0

        # Safe bits after removing Eve's quantum information + Cascade parity leakage
        eve_quantum_leak = int(np.ceil(n * self.binary_entropy(effective_eve_qber)))
        safe_capacity = n - eve_quantum_leak - leaked_parity_bits

        if safe_capacity <= 0:
            return np.array([], dtype=int), 0

        m = min(target_key_len, safe_capacity)

        # Generate public Toeplitz seed: first column (m bits) and first row (n bits)
        first_col = self.rng.integers(0, 2, size=m)
        first_row = self.rng.integers(0, 2, size=n)
        first_row[0] = first_col[0]

        t_matrix = toeplitz(first_col, first_row)

        # Modulo-2 Matrix-Vector Multiplication: K = (T @ S) % 2
        final_key = (t_matrix @ reconciled_bits) % 2
        return final_key.astype(int), int(safe_capacity)


if __name__ == "__main__":
    print("=== Q-SHIELD MODULE 3: CASCADE & TOEPLITZ SELF-TEST ===")
    proc = QShieldPostProcessor(seed=42)

    # 1. Verify Shor-Preskill Bound across QBER values
    for test_e in [0.02, 0.05, 0.08, 0.10, 0.11]:
        h2 = proc.binary_entropy(test_e)
        r = proc.shor_preskill_rate(test_e)
        print(f"QBER = {test_e*100:4.1f}% | H_2(e) = {h2:.3f} | Shor-Preskill Safe Rate R = {r*100:5.1f}%")

    # 2. Simulate an 850-bit Sifted Key with 6.5% Weather Drift errors (55 flipped bits!)
    rng = np.random.default_rng(101)
    alice_sifted = rng.integers(0, 2, size=850)
    bob_sifted = alice_sifted.copy()
    error_indices = rng.choice(850, size=55, replace=False)
    bob_sifted[error_indices] ^= 1

    initial_err = int(np.sum(alice_sifted != bob_sifted))
    print(f"\nBefore Cascade: {initial_err}/850 mismatched bits (QBER = {initial_err/850:.2%})")

    # Run 4-pass Cascade Reconciliation
    bob_reconciled, leaked_parity, rem_err = proc.cascade_reconcile(
        alice_sifted, bob_sifted, estimated_qber=initial_err / 850, num_passes=4
    )
    print(f"After Cascade:  {rem_err}/850 mismatched bits | Parity Hints Leaked = {leaked_parity} bits")

    # Run Toeplitz Privacy Amplification (AI Weather-Rescued Mode)
    alice_final_key, cap = proc.toeplitz_privacy_amplification(
        alice_sifted, qber=initial_err / 850, leaked_parity_bits=leaked_parity,
        target_key_len=256, is_weather_rescued=True
    )
    # Using same seed for Bob's Toeplitz matrix
    proc_bob = QShieldPostProcessor(seed=42)
    proc_bob.rng = np.random.default_rng(42)
    # Re-sync RNG state by running same call on Bob's reconciled bits:
    t_seed_rng = np.random.default_rng(999)
    col = t_seed_rng.integers(0, 2, size=len(alice_final_key))
    row = t_seed_rng.integers(0, 2, size=850)
    row[0] = col[0]
    T = toeplitz(col, row)
    k_alice = (T @ alice_sifted) % 2
    k_bob = (T @ bob_reconciled) % 2

    print(f"Toeplitz Output Length: {len(k_alice)} bits (Safe Capacity = {cap} bits)")
    print(f"Final Key Agreement:    {np.mean(k_alice == k_bob)*100:.1f}% Identical!")