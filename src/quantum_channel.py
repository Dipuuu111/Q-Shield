from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, phase_damping_error, depolarizing_error
import numpy as np


class QShieldQuantumChannel:
    """
    Module 1 of Q-Shield: 6-State BB84 Quantum Channel Simulator using Qiskit-Aer.
    Supports Z (Rectilinear), X (Diagonal), and Y (Circular Trap) bases.
    """

    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)
        self.base_sim = AerSimulator()

    def _build_noise_model(self, phase_damping_prob=0.0, depol_prob=0.01):
        """
        Builds a real Qiskit-Aer quantum physics NoiseModel for optical fiber.
        - phase_damping_error(gamma): Twists qubit phase around Z-axis (T2 thermal/weather drift).
          Crucially: Leaves Z-basis (|0>, |1>) untouched, but flips X-basis (|+>, |->) and Y-basis!
        - depolarizing_error(p): Baseline optical detector dark count / alignment error.
        """
        noise_model = NoiseModel()
        # Combine phase damping (weather) and minor depolarization (baseline hardware noise)
        fiber_error = phase_damping_error(phase_damping_prob).compose(
            depolarizing_error(depol_prob, 1)
        )
        # Attach the physical fiber noise strictly to the 'id' (fiber transit) gate!
        noise_model.add_all_qubit_quantum_error(fiber_error, ['id'])
        return noise_model

    @staticmethod
    def _create_photon_circuit(alice_bit, alice_basis, bob_basis, eve_basis=None, spy_flip=False):
        """
        Constructs the exact 1-qubit QuantumCircuit for a single photon transit.
        Bases: 0 = 'Z' (Vertical/Horizontal), 1 = 'X' (Diagonal), 2 = 'Y' (Circular Trap)
        """
        qc = QuantumCircuit(1, 2)  # 1 Qubit, 2 Classical bits (c[0]=Eve, c[1]=Bob)

        # 1. ALICE STATE PREPARATION
        if alice_bit == 1:
            qc.x(0)  # Flip |0> -> |1>

        if alice_basis == 1:      # X-Basis
            qc.h(0)
        elif alice_basis == 2:    # Y-Basis (Circular Trap)
            qc.h(0)
            qc.s(0)

        # 2. FIBER TRANSMISSION GATE (Qiskit NoiseModel attaches here!)
        qc.id(0)

        # 3. ADVERSARY INTERACTION (If Eve or Spy is active on this photon)
        if eve_basis is not None:
            # Step A: Rotate to Eve's guessed basis to read
            if eve_basis == 1:
                qc.h(0)
            elif eve_basis == 2:
                qc.sdg(0)
                qc.h(0)

            qc.measure(0, 0)  # Projective Collapse! Superposition is destroyed.

            # Step B: Rotate back to Eve's basis to resend to Bob
            if eve_basis == 1:
                qc.h(0)
            elif eve_basis == 2:
                qc.h(0)
                qc.s(0)

        if spy_flip:
            # Byzantine Saboteur: Blindly applies Pauli-X bit flip without measuring
            qc.x(0)

        # 4. BOB BASIS MEASUREMENT
        if bob_basis == 1:        # X-Basis
            qc.h(0)
        elif bob_basis == 2:      # Y-Basis
            qc.sdg(0)
            qc.h(0)

        qc.measure(0, 1)          # Bob's detector click saved in classical bit c[1]
        return qc

    def transmit_block(self, n_pulses=2000, scenario="clean"):
        """
        Transmits a block of n_pulses through Qiskit-Aer and returns sifted arrays.
        Scenarios: 'clean', 'weather_drift', 'naive_eve', 'mimicry_eve', 'spy_sabotage'
        """
        alice_bits = self.rng.integers(0, 2, size=n_pulses)
        # 45% Z-basis (0), 45% X-basis (1), 10% Y-basis Tomographic Trap (2)
        alice_bases = self.rng.choice([0, 1, 2], size=n_pulses, p=[0.45, 0.45, 0.10])
        bob_bases = self.rng.choice([0, 1, 2], size=n_pulses, p=[0.45, 0.45, 0.10])

        # Configure physical channel noise & adversary behavior per scenario
        eve_bases = [None] * n_pulses
        spy_flips = np.zeros(n_pulses, dtype=bool)
        phase_drift = 0.02  # Mild baseline fiber drift

        if scenario == "weather_drift":
            phase_drift = 0.32  # Heavy mountain fiber T2 phase damping!

        elif scenario == "naive_eve":
            # Eve intercepts 40% of photons, guessing randomly between Z (0) and X (1)
            intercept_mask = self.rng.random(n_pulses) < 0.40
            for idx in np.where(intercept_mask)[0]:
                eve_bases[idx] = int(self.rng.choice([0, 1]))

        elif scenario == "mimicry_eve":
            # Smart Eve: Measures ONLY in Z-basis (0) to fake E_X > E_Z like weather drift,
            # plus launches a concentrated 30-photon micro-burst tap in the middle!
            intercept_mask = self.rng.random(n_pulses) < 0.25
            intercept_mask[400:430] = True
            for idx in np.where(intercept_mask)[0]:
                eve_bases[idx] = 0  # Biased Z-only measurement!

        elif scenario == "spy_sabotage":
            # Spy blindly flips 6 random pulses using a Pauli-X modulator
            flip_indices = self.rng.choice(n_pulses, size=6, replace=False)
            spy_flips[flip_indices] = True

        noise_model = self._build_noise_model(phase_damping_prob=phase_drift, depol_prob=0.015)

        # Group identical circuit configurations for ultra-fast batch execution in Qiskit-Aer
        bob_measured_bits = np.zeros(n_pulses, dtype=int)
        configs = {}
        for i in range(n_pulses):
            key = (int(alice_bits[i]), int(alice_bases[i]), int(bob_bases[i]), eve_bases[i], bool(spy_flips[i]))
            configs.setdefault(key, []).append(i)

        for (a_bit, a_bas, b_bas, e_bas, s_flip), indices in configs.items():
            qc = self._create_photon_circuit(a_bit, a_bas, b_bas, e_bas, s_flip)
            result = self.base_sim.run(
                qc, noise_model=noise_model, shots=len(indices), memory=True
            ).result()
            # Qiskit bitstring format is "c[1]c[0]", so index [0] of string is Bob's bit c[1]!
            memories = result.get_memory()
            for idx, bit_str in zip(indices, memories):
                bob_measured_bits[idx] = int(bit_str[0])

        # Sifting: Keep only pulses where Alice and Bob picked the EXACT same basis
        sift_mask = (alice_bases == bob_bases)
        return (
            alice_bits[sift_mask],
            bob_measured_bits[sift_mask],
            alice_bases[sift_mask]
        )


# Quick verification test when you click 'Run' in PyCharm!
if __name__ == "__main__":
    channel = QShieldQuantumChannel()
    for mode in ["clean", "weather_drift", "naive_eve", "mimicry_eve", "spy_sabotage"]:
        a_sift, b_sift, bases = channel.transmit_block(n_pulses=2000, scenario=mode)
        errors = (a_sift != b_sift)
        ez = errors[bases == 0].mean() * 100
        ex = errors[bases == 1].mean() * 100
        ey = errors[bases == 2].mean() * 100
        print(f"[{mode.upper():13s}] Sifted={len(a_sift)} bits | "
              f"E_Z={ez:5.2f}% | E_X={ex:5.2f}% | E_Y(Trap)={ey:5.2f}%")