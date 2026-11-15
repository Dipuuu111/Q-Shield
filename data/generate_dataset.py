
import csv
import random

# Make results reproducible
random.seed(42)

# Output CSV file
output_file = "data/qshield_telemetry.csv"

# CSV column names
columns = [
    "e_z",
    "e_x",
    "e_y",
    "basis_asymmetry",
    "window_20_peak",
    "bloch_coherence",
    "label"
]

# Five channel states
states = {
    0: "Clean_Channel",
    1: "Weather_Phase_Drift",
    2: "Naive_Eve_Intercept",
    3: "Smart_Mimicry_Or_MicroBurst_Eve",
    4: "Spy_BitFlip_Sabotage"
}

rows = []

# Generate 200 samples for each state
for label in states:

    for _ in range(200):

        if label == 0:
            e_z = random.uniform(0.5, 2.0)
            e_x = random.uniform(0.5, 2.0)
            e_y = random.uniform(0.85, 1.0)
            window_peak = random.uniform(1, 5)
            coherence = random.uniform(0.90, 1.0)

        elif label == 1:
            e_z = random.uniform(1.0, 3.0)
            e_x = random.uniform(5.0, 10.0)
            e_y = random.uniform(0.85, 1.0)
            window_peak = random.uniform(3, 8)
            coherence = random.uniform(0.75, 0.95)

        elif label == 2:
            e_z = random.uniform(8.0, 15.0)
            e_x = random.uniform(8.0, 15.0)
            e_y = random.uniform(0.40, 0.70)
            window_peak = random.uniform(10, 20)
            coherence = random.uniform(0.30, 0.60)

        elif label == 3:
            e_z = random.uniform(2.0, 6.0)
            e_x = random.uniform(2.0, 6.0)
            e_y = random.uniform(0.05, 0.30)
            window_peak = random.uniform(20, 35)
            coherence = random.uniform(0.10, 0.40)

        else:
            e_z = random.uniform(2.0, 6.0)
            e_x = random.uniform(2.0, 6.0)
            e_y = random.uniform(0.50, 0.80)
            window_peak = random.uniform(3, 10)
            coherence = random.uniform(0.40, 0.70)

        basis_asymmetry = abs(e_x - e_z)

        rows.append([
            round(e_z, 3),
            round(e_x, 3),
            round(e_y, 3),
            round(basis_asymmetry, 3),
            round(window_peak, 3),
            round(coherence, 3),
            label
        ])

# Shuffle samples
random.shuffle(rows)

# Write the CSV file
with open(output_file, "w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(columns)
    writer.writerows(rows)

print("DATASET GENERATED SUCCESSFULLY!")
print("Total samples:", len(rows))
print("Classes:", len(states))
print("File saved at:", output_file)
