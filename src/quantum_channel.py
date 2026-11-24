from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, phase_damping_error, depolarizing_error
import numpy as np


class QShieldQuantumChannel:
    def __init__(self, seed=42):
        self.rng = np.random.default_rng(seed)
        self.base_sim = AerSimulator()

    def _build_noise_model(self, phase_damping_prob=0.0, depol_prob=0.01):
        noise_model = NoiseModel()
        fiber_error = phase_damping_error(phase_damping_prob).compose(
            depolarizing_error(depol_prob, 1)
        )
        # Attach fiber noise strictly to the identity (transit) gate
        noise_model.add_all_qubit_quantum_error(fiber_error, ['id'])
        return noise_model

    @staticmethod
    def _create_photon_circuit(alice_bit, alice_basis, bob_basis, eve_basis=None, spy_flip=False):
        qc = QuantumCircuit(1, 2)

        if alice_bit == 1:
            qc.x(0)

        if alice_basis == 1:
            qc.h(0)
        elif alice_basis == 2:
            qc.h(0)
            qc.s(0)

        qc.id(0)

        if eve_basis is not None:
            if eve_basis == 1:
                qc.h(0)
            elif eve_basis == 2:
                qc.sdg(0)
                qc.h(0)

            qc.measure(0, 0)

            if eve_basis == 1:
                qc.h(0)
            elif eve_basis == 2:
                qc.h(0)
                qc.s(0)

        if spy_flip:
            qc.x(0)

        if bob_basis == 1:
            qc.h(0)
        elif bob_basis == 2:
            qc.sdg(0)
            qc.h(0)

        qc.measure(0, 1)
        return qc

    def transmit_block(self, n_pulses=2000, scenario="clean"):
        alice_bits = self.rng.integers(0, 2, size=n_pulses)
        alice_bases = self.rng.choice([0, 1, 2], size=n_pulses, p=[0.45, 0.45, 0.10])
        bob_bases = self.rng.choice([0, 1, 2], size=n_pulses, p=[0.45, 0.45, 0.10])

        eve_bases = [None] * n_pulses
        spy_flips = np.zeros(n_pulses, dtype=bool)
        phase_drift = 0.02

        if scenario == "weather_drift":
            phase_drift = 0.32
        elif scenario == "naive_eve":
            intercept_mask = self.rng.random(n_pulses) < 0.40
            for idx in np.where(intercept_mask)[0]:
                eve_bases[idx] = int(self.rng.choice([0, 1]))
        elif scenario == "mimicry_eve":
            intercept_mask = self.rng.random(n_pulses) < 0.25
            intercept_mask[400:430] = True
            for idx in np.where(intercept_mask)[0]:
                eve_bases[idx] = 0
        elif scenario == "spy_sabotage":
            flip_indices = self.rng.choice(n_pulses, size=6, replace=False)
            spy_flips[flip_indices] = True

        noise_model = self._build_noise_model(phase_damping_prob=phase_drift, depol_prob=0.015)

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
            # Qiskit returns classical bits in reverse order ("c[1]c[0]"), so index 0 is Bob's c[1]
            memories = result.get_memory()
            for idx, bit_str in zip(indices, memories):
                bob_measured_bits[idx] = int(bit_str[0])

        sift_mask = (alice_bases == bob_bases)
        return (
            alice_bits[sift_mask],
            bob_measured_bits[sift_mask],
            alice_bases[sift_mask]
        )


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
