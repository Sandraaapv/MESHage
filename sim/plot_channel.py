"""
plot channel model curves: distance vs received power and success probability
"""
import os
import sys

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib.pyplot as plt
import numpy as np
from sim.channel import WirelessChannel


def main():
    distances = np.linspace(1, 80, 200)
    colors = {2: "#22c55e", 3: "#0284c7", 4: "#ef4444"}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    for n in [2, 3, 4]:
        channel = WirelessChannel(n=n)
        prx = [channel.received_power(d, shadowing=False) for d in distances]
        prob = [channel.packet_success_from_distance(d, shadowing=False) for d in distances]

        ax1.plot(distances, prx, label=f"n = {n}", color=colors[n], linewidth=2.2)
        ax2.plot(distances, prob, label=f"n = {n}", color=colors[n], linewidth=2.2)

    # received power plot formatting
    ax1.axhline(
        -85.0,
        color="#64748b",
        linestyle="--",
        label="Sensitivity (-85 dBm)",
    )
    ax1.set_xlabel("Distance (m)")
    ax1.set_ylabel("Received Power (dBm)")
    ax1.set_title("Distance vs Received Power")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper right")

    # success probability plot formatting
    ax2.set_xlabel("Distance (m)")
    ax2.set_ylabel("Packet Success Probability")
    ax2.set_title("Distance vs Success Probability")
    ax2.set_ylim(-0.05, 1.05)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="lower left")

    plt.tight_layout()

    # save plot to results
    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "channel_plots.png")
    plt.savefig(out_file, dpi=150)
    print(f"Channel plots saved to {out_file}")

    if "--no-show" not in sys.argv:
        try:
            plt.show()
        except Exception:
            pass


if __name__ == "__main__":
    main()
