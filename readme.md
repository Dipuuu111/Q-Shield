# Q-Shield

**An AI-Driven Adaptive Hybrid Quantum Key Distribution (BB84) and Post-Quantum Cryptographic (NIST FIPS 203 ML-KEM) Orchestrator for Tactical Communications**

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Qiskit](https://img.shields.io/badge/IBM%20Qiskit-Aer%20Simulator-6929C4)
![PQC](https://img.shields.io/badge/NIST%20FIPS%20203-ML--KEM%20Prototype-008080)
![License](https://img.shields.io/badge/License-AGPL--3.0-green)

---

## Overview

Standard Quantum Key Distribution (**BB84**) provides information-theoretic security governed by the No-Cloning Theorem, yet suffers from three major operational vulnerabilities in field-deployed tactical fiber networks:

1. **False-Alarm Blackouts:** Thermal fluctuations and mechanical stress induce $T_2$ phase damping in optical fibers, pushing the Quantum Bit Error Rate ($\text{QBER}$) toward the $11\%$ Shor-Preskill limit. Standard BB84 mistakes natural weather drift for an eavesdropper and aborts the link.
2. **Adversarial Mimicry & Micro-Bursts:** A basis-biased eavesdropper ("Smart Eve") can measure exclusively in the $Z$-basis to mimic weather asymmetry ($E_X \gg E_Z$), or intercept tiny $20$-bit micro-bursts that barely shift global QBER.
3. **Byzantine Bit-Flip Sabotage:** A blind saboteur injecting unmeasured Pauli-$X$ bit flips can leave residual key discrepancies that avalanche through privacy amplification, causing the receiver to decrypt garbled data.

**Q-Shield** addresses these vulnerabilities in a modular, pure-Python framework that combines a **6-State BB84 Qiskit-Aer simulator**, a **6-feature Scikit-Learn threat classifier**, **back-tracked Cascade reconciliation & Modulo-2 Toeplitz privacy amplification**, a **pre-decryption `SHA3-256` integrity gate**, and a **NIST FIPS 203 (`ML-KEM-768` / `ML-KEM-1024`) post-quantum failover engine**.

---

## System Architecture

```text
[1. Quantum Channel (src/quantum_channel.py)]
   2,000-photon 6-State BB84 (45% Z, 45% X, 10% Y Trap) via Qiskit-Aer
   NoiseModel: T2 Phase Damping + Depolarizing + Eve / Spy Injection
                                │
                                ▼
[2. Telemetry & AI Classifier (src/telemetry_generator.py & src/ml_classifier.py)]
   Extracts 6 features: [e_z, e_x, e_y, basis_asymmetry, window_20_peak, bloch_coherence]
   Random Forest classifies link into 5 operational/threat states:
     ├── Class 0 (Clean) / Class 1 (Weather Drift) ──► Keep QKD Alive
     └── Class 2 (Naive Eve) / Class 3 (Mimicry) / Class 4 (Sabotage) ──► Quarantine QKD
                                │
                                ▼
[3. Post-Processing (src/reconciliation_privacy.py)]
   • Shor-Preskill bound R = 1 - 2*H_2(e)
   • Multi-pass Cascade parity reconciliation with backtracking
   • Modulo-2 Toeplitz Matrix privacy amplification -> 256-bit K_QKD
                                │
                                ▼
[4. Anti-Sabotage Gate & Hybrid Crypto (src/hybrid_crypto.py)]
   • Pre-decryption check: SHA3-256(K_HQ) == SHA3-256(K_Border)
   • Hybrid Active : K_Master = HKDF-SHA3-256(K_QKD-256 || K_ML-KEM-768)
   • PQC Failover  : K_Master = HKDF-SHA3-256(K_ML-KEM-1024)
   • Payload Lock  : AES-256-GCM Authenticated Encryption
```

---

## Threat & Countermeasure Matrix

| Class | Scenario | Physical Signature | Standard BB84 Outcome | Q-Shield Countermeasure |
| :---: | :--- | :--- | :--- | :--- |
| **0** | **Clean Channel** | Low $E_Z, E_X, E_Y$; high Bloch coherence | Standard QKD only | **Hybrid Mode:** `QKD-256` + `ML-KEM-768` via `HKDF-SHA3-256` |
| **1** | **Weather Phase Drift** | Heavy $T_2$ dephasing: $E_X \approx E_Y \gg E_Z$, smooth window | False-alarm link abort | **AI Link Rescue:** Adaptive 6-pass Cascade + `ML-KEM-768` hybrid |
| **2** | **Naive Eve Intercept** | Random-basis measurement: symmetric $E_Z \approx E_X \approx E_Y$ | Link blackout (DoS) | **Quantum Quarantine:** Zero-downtime failover to `ML-KEM-1024` |
| **3** | **Smart Mimicry / Micro-Burst Eve** | $Z$-only tapping + localized burst: $Y$-trap collapse & high $\text{Window}_{20}$ | Evades global QBER threshold | **Tomographic Catch + Failover:** Quarantines QKD $\to$ `ML-KEM-1024`; Toeplitz crushes micro-leaks |
| **4** | **Byzantine Spy Sabotage** | Blind Pauli-$X$ bit flips inducing key desynchronization | Garbled AES decryption | **Pre-Decryption `SHA3-256` Gate:** Detects 1-bit mismatch & hot-swaps to `ML-KEM-1024` |

---

## Mathematical Foundations

1. **Quantum Phase Damping (Kraus Evolution):**
   Optical fiber $T_2$ thermal drift evolves the qubit density matrix $\rho \mapsto \sum_k E_k \rho E_k^\dagger$ with $E_0 = \begin{bmatrix} 1 & 0 \\ 0 & \sqrt{1-\gamma} \end{bmatrix}$ and $E_1 = \begin{bmatrix} 0 & 0 \\ 0 & \sqrt{\gamma} \end{bmatrix}$, leaving $Z$-basis populations untouched ($E_Z = 0$) while degrading equatorial bases at $E_X = E_Y = \frac{1 - \sqrt{1-\gamma}}{2}$.
2. **Bloch Equator Coherence:**
   $$C = \frac{\sqrt{(1 - 2E_X)^2 + (1 - 2E_Y)^2}}{\sqrt{2}}$$
3. **Shor-Preskill Secrecy Bound:**
   $$H_2(e) = -e\log_2(e) - (1-e)\log_2(1-e), \qquad R = \max\big(0,\; 1 - 2H_2(e)\big)$$
   At $e = 0.11$, $H_2(0.11) \approx 0.50 \implies R = 0$.
4. **Universal-2 Toeplitz Privacy Amplification:**
   $$K_{M \times 1} = \left(T_{M \times N} \cdot S_{N \times 1}\right) \bmod 2$$
   Defined by only $M + N - 1$ public seed bits.
5. **Module-LWE Key Encapsulation (`ML-KEM` Prototype):**
   Operates over the cyclotomic polynomial ring $R_q = \mathbb{Z}_{3329}[X]/(X^{256}+1)$ with Centered Binomial noise $\text{CBD}_2$ and rank $k=3$ (`ML-KEM-768`) or $k=4$ (`ML-KEM-1024`):
   $$\mathbf{t} = \mathbf{A}\mathbf{s} + \mathbf{e}, \quad \mathbf{u} = \mathbf{A}^T\mathbf{r} + \mathbf{e}_1, \quad v = \mathbf{t}^T\mathbf{r} + e_2 + \lceil q/2 \rfloor \cdot m \pmod{3329}$$
   *(Note: `src/hybrid_crypto.py` implements a self-contained mathematical prototype of Module-LWE `K-PKE` for educational and research benchmarking; production deployments should pair with a certified FIPS 203 binary incorporating full radix-2 NTT, ciphertext compression, and the Fujisaki-Okamoto `IND-CCA2` transform.)*

---

## Repository Structure

```text
Q-Shield/
├── main.py                         # End-to-end 5-scenario pipeline orchestrator
├── requirements.txt                # Python dependencies
├── CITATION.cff                    # Academic citation metadata
├── LICENSE                         # GNU AGPL-3.0 License
├── data/
│   └── qshield_telemetry.csv       # Generated 5,000-block (10M-photon) telemetry dataset
├── models/
│   └── qshield_classifier.joblib   # Trained best-performing Scikit-Learn classifier
└── src/
    ├── quantum_channel.py          # Module 1: 6-State BB84 Qiskit-Aer simulator
    ├── telemetry_generator.py      # Module 2: 6-feature extractor & Kraus dataset generator
    ├── reconciliation_privacy.py   # Module 3: Shor-Preskill, Cascade, & Toeplitz hashing
    ├── hybrid_crypto.py            # Module 4: Module-LWE ML-KEM, SHA3 gate, HKDF, AES-256-GCM
    └── ml_classifier.py            # Module 5: RF / DT / HistGB training & inference
```

---

## Installation & Quick Start

### 1. Environment Setup
```bash
git clone https://github.com/Dipuuu111/Q-Shield.git
cd Q-Shield
pip install -r requirements.txt
```

### 2. Generate Real Qiskit Telemetry Dataset (10M Photons)
```bash
python src/telemetry_generator.py
```
This exports 5,000 labeled blocks (1,000 per class) into `data/qshield_telemetry.csv`.

### 3. Train & Benchmark the ML Classifiers
```bash
python src/ml_classifier.py
```
Benchmarks Random Forest, Decision Tree, and Histogram Gradient Boosting, prints the classification report and confusion matrix, and saves the winning model to `models/qshield_classifier.joblib`.

### 4. Run the End-to-End Q-Shield Pipeline
```bash
python main.py
```
Executes all 5 tactical scenarios (`clean`, `weather_drift`, `naive_eve`, `mimicry_eve`, `spy_sabotage`) from Qiskit photon transmission through `AES-256-GCM` decryption and verifies hybrid activation vs. `ML-KEM-1024` failover.

---

## Project Roadmap

- [x] **Module 1:** 6-State BB84 Qiskit-Aer simulator with $T_2$ phase damping & adversarial injection (`src/quantum_channel.py`)
- [x] **Module 2:** Vectorized Kraus telemetry & 6-feature dataset generator (`src/telemetry_generator.py`)
- [x] **Module 3:** Back-tracked Cascade reconciliation & Modulo-2 Toeplitz privacy amplification (`src/reconciliation_privacy.py`)
- [x] **Module 4:** Polynomial-ring Module-LWE (`ML-KEM-768/1024`), `SHA3-256` gate, `HKDF-SHA3-256`, & `AES-256-GCM` (`src/hybrid_crypto.py`)
- [x] **Module 5:** Multi-model Scikit-Learn threat classifier (`src/ml_classifier.py`) & end-to-end orchestrator (`main.py`)
- [ ] **Upcoming:** 300-DPI evaluation plots (`src/generate_plots.py`), `Argon2id` terminal key wrapping (`src/argon_guard.py`), and interactive Streamlit Command Dashboard (`app.py`)

---

## Citation & License

This project is licensed under the **GNU Affero General Public License v3.0 (`AGPL-3.0`)** — see the [LICENSE](LICENSE) file for details.

If you use or build upon Q-Shield in your research, please cite it using the included `CITATION.cff` file:

```bibtex
@software{pandey2026qshield,
  author       = {Pandey, Diptanshu},
  title        = {Q-Shield: An AI-Driven Adaptive Hybrid QKD and Post-Quantum Cryptographic System for Tactical Communications},
  year         = {2026},
  version      = {0.1.0},
  institution  = {Vishwakarma Institute of Technology, Pune},
  url          = {https://github.com/Dipuuu111/Q-Shield}
}
```