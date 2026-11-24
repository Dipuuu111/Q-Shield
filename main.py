import numpy as np

from src.quantum_channel import QShieldQuantumChannel
from src.telemetry_generator import QShieldTelemetryGenerator
from src.ml_classifier import FEATURE_COLUMNS, predict_channel
from src.reconciliation_privacy import QShieldPostProcessor
from src.hybrid_crypto import QShieldHybridCrypto


def run_qshield_session(scenario: str, message: str, n_pulses: int = 2000, seed: int = 42):
    channel = QShieldQuantumChannel(seed=seed)
    post_proc = QShieldPostProcessor(seed=seed)
    crypto = QShieldHybridCrypto()

    alice_sifted, bob_sifted, bases_sifted = channel.transmit_block(
        n_pulses=n_pulses, scenario=scenario
    )

    feature_list = QShieldTelemetryGenerator.compute_features(
        alice_sifted, bob_sifted, bases_sifted
    )
    feature_dict = dict(zip(FEATURE_COLUMNS, feature_list))
    prediction = predict_channel(feature_dict)
    ai_class = prediction["label"]

    qber = float(np.mean(alice_sifted != bob_sifted)) if len(alice_sifted) > 0 else 1.0
    k_alice = np.array([], dtype=int)
    k_bob = np.array([], dtype=int)
    leaked_parity = 0
    rem_errors = 0

    if ai_class in (0, 1):
        num_passes = 6 if ai_class == 1 else 4
        bob_reconciled, leaked_parity, rem_errors = post_proc.cascade_reconcile(
            alice_sifted, bob_sifted, estimated_qber=qber, num_passes=num_passes
        )
        weather_rescued = (ai_class == 1)
        k_alice, _ = post_proc.toeplitz_privacy_amplification(
            alice_sifted,
            qber=qber,
            leaked_parity_bits=leaked_parity,
            target_key_len=256,
            is_weather_rescued=weather_rescued,
            matrix_seed=999
        )
        k_bob, _ = post_proc.toeplitz_privacy_amplification(
            bob_reconciled,
            qber=qber,
            leaked_parity_bits=leaked_parity,
            target_key_len=256,
            is_weather_rescued=weather_rescued,
            matrix_seed=999
        )

    handshake = crypto.establish_hybrid_master_key(k_alice, k_bob, ai_class=ai_class)
    packet = crypto.encrypt_tactical_message(handshake["k_master"], message)
    decrypted = crypto.decrypt_tactical_message(
        handshake["k_master"], packet["raw_nonce"], packet["raw_ciphertext"]
    )

    return {
        "scenario": scenario,
        "sifted_bits": len(alice_sifted),
        "qber": qber,
        "ai_state": prediction["channel_state"],
        "ai_class": ai_class,
        "leaked_parity": leaked_parity,
        "remaining_errors": rem_errors,
        "qkd_key_bits": len(k_alice),
        "mode_status": handshake["mode_status"],
        "sha3_verified": handshake["sha3_verified"],
        "decrypted_ok": decrypted == message,
    }


if __name__ == "__main__":
    tactical_msg = "SECTOR-4 RADAR ALERT: PATROL UNIT ALPHA PROCEED TO GRID 78-N"
    scenarios = ["clean", "weather_drift", "naive_eve", "mimicry_eve", "spy_sabotage"]

    print("=== Q-SHIELD END-TO-END PIPELINE VERIFICATION ===")
    for mode in scenarios:
        res = run_qshield_session(scenario=mode, message=tactical_msg)
        print(f"\n[{res['scenario'].upper()}]")
        print(f"  Sifted Bits:    {res['sifted_bits']} | Raw QBER: {res['qber']*100:.2f}%")
        print(f"  AI Prediction:  Class {res['ai_class']} ({res['ai_state']})")
        print(f"  Post-Process:   Leaked={res['leaked_parity']} bits | Residual Err={res['remaining_errors']} | QKD Key={res['qkd_key_bits']} bits")
        print(f"  Crypto Mode:    {res['mode_status']}")
        print(f"  SHA3 Sync:      {res['sha3_verified']} | AES-256-GCM Decrypted OK: {res['decrypted_ok']}")