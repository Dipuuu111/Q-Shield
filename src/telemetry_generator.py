import os
import csv
import time
import numpy as np
from qiskit_aer.noise import phase_damping_error, depolarizing_error
from qiskit.quantum_info import DensityMatrix, Operator
from qiskit import QuantumCircuit


class QShieldTelemetryGenerator:
    """
    Module 2 of Q-Shield: High-Throughput Quantum Telemetry & Feature Extractor.
    Extracts the 6 physical-layer features specified in the Q-Shield Handbook:
      [e_z, e_x, e_y, basis_asymmetry, window_20_peak, bloch_coherence]
    and exports 5,000 labeled blocks (10,000,000 simulated photons) to
    data/qshield_telemetry.csv.
    """

    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)

    @staticmethod
    def compute_features(alice_sifted, bob_sifted, bases_sifted):
        """
        Extracts the 6 core telemetry features from a sifted photon block.
        """
        errors = (alice_sifted != bob_sifted).astype(float)

        # 1-3. Basis-specific error rates (Z=0, X=1, Y=2)
        z_mask = (bases_sifted == 0)
        x_mask = (bases_sifted == 1)
        y_mask = (bases_sifted == 2)

        e_z = float(errors[z_mask].mean()) if np.any(z_mask) else 0.0
        e_x = float(errors[x_mask].mean()) if np.any(x_mask) else 0.0
        e_y = float(errors[y_mask].mean()) if np.any(y_mask) else 0.0

        # 4. Basis Asymmetry |E_X - E_Z|
        basis_asymmetry = float(abs(e_x - e_z))

        # 5. 20-Bit Sliding Window Peak QBER
        window_size = 20
        if len(errors) >= window_size:
            sliding_means = np.convolve(
                errors, np.ones(window_size) / window_size, mode='valid'
            )
            window_20_peak = float(sliding_means.max())
        else:
            window_20_peak = float(errors.mean()) if len(errors) > 0 else 0.0

        # 6. Bloch Equator Coherence C = sqrt((1 - 2*E_X)^2 + (1 - 2*E_Y)^2) / sqrt(2)
        rx = 1.0 - 2.0 * e_x
        ry = 1.0 - 2.0 * e_y
        bloch_coherence = float(np.sqrt(rx**2 + ry**2) / np.sqrt(2.0))

        return [
            round(e_z, 5),
            round(e_x, 5),
            round(e_y, 5),
            round(basis_asymmetry, 5),
            round(window_20_peak, 5),
            round(bloch_coherence, 5),
        ]

    def _qiskit_basis_error_probs(self, gamma_phase, p_depol):
        """
        Uses Qiskit's DensityMatrix and Kraus noise operators (phase_damping +
        depolarizing) to calculate exact physical bit-flip probabilities in Z, X, and Y.
        """
        channel = phase_damping_error(gamma_phase).compose(
            depolarizing_error(p_depol, 1)
        )

        # Z-basis: Prepare |0>, evolve through Qiskit noise channel, prob of |1>
        dm_z = DensityMatrix.from_label('0').evolve(channel)
        p_err_z = float(np.real(dm_z.data[1, 1]))

        # X-basis: Prepare |+>, evolve through noise channel, measure in X
        dm_x = DensityMatrix.from_label('+').evolve(channel)
        qc_h = QuantumCircuit(1)
        qc_h.h(0)
        dm_x_meas = dm_x.evolve(Operator(qc_h))
        p_err_x = float(np.real(dm_x_meas.data[1, 1]))

        # Y-basis: Prepare |r> (|+i>), evolve through noise channel, measure in Y
        dm_y = DensityMatrix.from_label('r').evolve(channel)
        qc_y = QuantumCircuit(1)
        qc_y.sdg(0)
        qc_y.h(0)
        dm_y_meas = dm_y.evolve(Operator(qc_y))
        p_err_y = float(np.real(dm_y_meas.data[1, 1]))

        return p_err_z, p_err_x, p_err_y

    def simulate_block_fast(self, n_pulses=2000, label=0):
        """
        Simulates a 2,000-photon block using exact Qiskit Kraus probabilities.
        Labels:
          0 = Clean
          1 = Weather_Drift
          2 = Naive_Eve
          3 = Mimicry_Eve
          4 = Spy_Sabotage
        """
        alice_bits = self.rng.integers(0, 2, size=n_pulses)
        alice_bases = self.rng.choice([0, 1, 2], size=n_pulses, p=[0.45, 0.45, 0.10])
        bob_bases = self.rng.choice([0, 1, 2], size=n_pulses, p=[0.45, 0.45, 0.10])

        gamma_phase = self.rng.uniform(0.005, 0.035)
        p_depol = self.rng.uniform(0.008, 0.020)

        if label == 1:  # Weather Drift (Heavy T2 Phase Damping)
            gamma_phase = self.rng.uniform(0.14, 0.42)
            p_depol = self.rng.uniform(0.010, 0.025)

        p_err_z, p_err_x, p_err_y = self._qiskit_basis_error_probs(gamma_phase, p_depol)
        base_err_lookup = np.array([p_err_z, p_err_x, p_err_y])

        sift_mask = (alice_bases == bob_bases)
        a_sift = alice_bits[sift_mask]
        b_bas = bob_bases[sift_mask]
        n_sift = len(a_sift)

        flip_probs = base_err_lookup[b_bas]
        flips = self.rng.random(n_sift) < flip_probs
        b_sift = np.bitwise_xor(a_sift, flips.astype(int))

        if label == 2:  # Naive Eve (Random intercept across stream)
            intercept_rate = self.rng.uniform(0.18, 0.55)
            eve_taps = self.rng.random(n_sift) < intercept_rate
            eve_wrong_basis = eve_taps & (self.rng.random(n_sift) < 0.60)
            eve_flips = eve_wrong_basis & (self.rng.random(n_sift) < 0.50)
            b_sift = np.bitwise_xor(b_sift, eve_flips.astype(int))

        elif label == 3:  # Smart Mimicry / Micro-Burst Eve
            tap_rate = self.rng.uniform(0.12, 0.30)
            eve_taps = self.rng.random(n_sift) < tap_rate
            if n_sift > 60:
                burst_start = self.rng.integers(10, n_sift - 35)
                burst_len = self.rng.integers(18, 32)
                eve_taps[burst_start:burst_start + burst_len] = True

            non_z_taps = eve_taps & (b_bas != 0)
            eve_flips = non_z_taps & (self.rng.random(n_sift) < 0.50)
            y_taps = eve_taps & (b_bas == 2)
            y_extra_flips = y_taps & (self.rng.random(n_sift) < 0.75)
            b_sift = np.bitwise_xor(b_sift, (eve_flips | y_extra_flips).astype(int))

        elif label == 4:  # Byzantine Spy Sabotage (Concentrated Pauli-X Bit Flips)
            if n_sift > 40:
                burst_start = self.rng.integers(5, n_sift - 25)
                n_flips = self.rng.integers(5, 11)
                sabotage_idx = self.rng.choice(
                    np.arange(burst_start, burst_start + 20),
                    size=min(n_flips, 20),
                    replace=False
                )
                b_sift[sabotage_idx] ^= 1

        features = self.compute_features(a_sift, b_sift, b_bas)
        return features + [label]

    def generate_dataset(self, output_csv_path, samples_per_class=1000, n_pulses=2000):
        """
        Generates 5 * samples_per_class rows (5,000 blocks = 10,000,000 photons)
        and saves to data/qshield_telemetry.csv.
        """
        os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)
        header = [
            "e_z", "e_x", "e_y", "basis_asymmetry",
            "window_20_peak", "bloch_coherence", "label"
        ]

        total_rows = samples_per_class * 5
        print(f"Generating {total_rows} blocks ({total_rows * n_pulses:,} simulated photons)...")
        start_t = time.time()

        rows = []
        for label in range(5):
            for _ in range(samples_per_class):
                rows.append(self.simulate_block_fast(n_pulses=n_pulses, label=label))

        self.rng.shuffle(rows)

        with open(output_csv_path, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

        elapsed = time.time() - start_t
        print(f"Done in {elapsed:.2f}s! Saved to: {output_csv_path}")


if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(project_root, "data", "qshield_telemetry.csv")

    gen = QShieldTelemetryGenerator(seed=42)
    gen.generate_dataset(csv_path, samples_per_class=1000, n_pulses=2000)