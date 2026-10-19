"""
run all simulation experiments and generate figures and csv reports
"""
import csv
import math
import os
import random
import sys
import time
from typing import Dict, List, Tuple

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from sim.channel import WirelessChannel
from sim.network import Network


def setup_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.labelweight": "bold",
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "lines.linewidth": 2.2,
        "lines.markersize": 6,
    })


def get_connected_pair(net: Network) -> Tuple[Optional[str], Optional[str], int]:
    g = nx.Graph()
    for name, node in net.nodes.items():
        for nbr in node.neighbors:
            g.add_edge(name, nbr)

    if not g.nodes():
        return None, None, 0

    components = sorted(nx.connected_components(g), key=len, reverse=True)
    if not components or len(components[0]) < 2:
        return None, None, 0

    sub = g.subgraph(components[0])
    spl = dict(nx.all_pairs_shortest_path_length(sub))
    max_d = 0
    src, dst = list(sub.nodes())[0], list(sub.nodes())[-1]
    for u in sub.nodes():
        for v in sub.nodes():
            if spl[u][v] > max_d:
                max_d = spl[u][v]
                src, dst = u, v
    return src, dst, max_d


# -------------------------------------------------------------
# Experiment 1: Routing Comparison
# -------------------------------------------------------------
def run_experiment_1(trials: int = 20) -> Dict[str, dict]:
    print("\n[1/4] Running Experiment 1: Routing Comparison (flooding vs shortest vs gossip)...")
    results = []
    routers = ["flooding", "shortest", "gossip"]

    for trial in range(trials):
        seed = 100 + trial
        random.seed(seed)
        channel = WirelessChannel(n=2.6, sigma=2.0)

        # generate consistent node positions for all 3 protocols in this trial
        node_positions = {
            f"N{i}": (random.uniform(5, 75), random.uniform(5, 75))
            for i in range(16)
        }

        # find connected endpoints on the topology
        temp_net = Network(transmission_range=32.0, channel=channel, seed=seed)
        for name, (x, y) in node_positions.items():
            temp_net.add_node(name, x, y)
        temp_net.build_links()
        src, dst, max_hops = get_connected_pair(temp_net)
        if not src or not dst or max_hops < 2:
            continue

        for rtype in routers:
            net = Network(transmission_range=32.0, channel=channel, default_router=rtype, seed=seed)
            for name, (x, y) in node_positions.items():
                net.add_node(name, x, y, router_type=rtype)
            net.build_links()

            # shortest path runs hello exchange first to learn topology
            if rtype == "shortest":
                for _ in range(3):
                    net.broadcast_hellos()
                    net.run()

            tx_before = net.total_transmissions
            net.send_message(src, dst, payload=f"exp1-{trial}")
            net.run()

            tx_msg = net.total_transmissions - tx_before
            deliv_list = net.nodes[dst].router.delivered_messages
            delivered = 1 if any(m.payload == f"exp1-{trial}" for m in deliv_list) else 0

            delay = 0
            for m in deliv_list:
                if m.payload == f"exp1-{trial}":
                    delay = max(1, len(m.path) - 1)
                    break

            results.append({
                "trial": trial,
                "seed": seed,
                "router": rtype,
                "delivered": delivered,
                "delay_hops": delay if delivered else 0,
                "packets_transmitted": tx_msg,
            })

    # save CSV
    csv_path = os.path.join("results", "exp1_routing_comparison.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["trial", "seed", "router", "delivered", "delay_hops", "packets_transmitted"])
        writer.writeheader()
        writer.writerows(results)

    # compute stats
    stats = {}
    for rtype in routers:
        r_rows = [r for r in results if r["router"] == rtype]
        deliv_rates = [r["delivered"] * 100 for r in r_rows]
        delays = [r["delay_hops"] for r in r_rows if r["delivered"] == 1]
        packets = [r["packets_transmitted"] for r in r_rows]
        stats[rtype] = {
            "delivery_rate_mean": np.mean(deliv_rates),
            "delivery_rate_std": np.std(deliv_rates),
            "delay_mean": np.mean(delays) if delays else 0.0,
            "delay_std": np.std(delays) if delays else 0.0,
            "packets_mean": np.mean(packets),
            "packets_std": np.std(packets),
        }

    # plot
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 4.5))
    x_pos = np.arange(len(routers))
    colors = ["#0284c7", "#10b981", "#f59e0b"]

    # delivery rate
    means = [stats[r]["delivery_rate_mean"] for r in routers]
    stds = [stats[r]["delivery_rate_std"] for r in routers]
    ax1.bar(x_pos, means, yerr=stds, capsize=4, color=colors, alpha=0.85, edgecolor="#334155")
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(["Flooding", "Shortest Path", "Gossip"])
    ax1.set_ylabel("Delivery Rate (%)")
    ax1.set_title("Delivery Rate")
    ax1.set_ylim(0, 110)
    ax1.grid(True, linestyle=":", alpha=0.5, axis="y")

    # average delay
    means = [stats[r]["delay_mean"] for r in routers]
    stds = [stats[r]["delay_std"] for r in routers]
    ax2.bar(x_pos, means, yerr=stds, capsize=4, color=colors, alpha=0.85, edgecolor="#334155")
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(["Flooding", "Shortest Path", "Gossip"])
    ax2.set_ylabel("Average Delay (hops)")
    ax2.set_title("Average Delay")
    ax2.grid(True, linestyle=":", alpha=0.5, axis="y")

    # packets transmitted
    means = [stats[r]["packets_mean"] for r in routers]
    stds = [stats[r]["packets_std"] for r in routers]
    ax3.bar(x_pos, means, yerr=stds, capsize=4, color=colors, alpha=0.85, edgecolor="#334155")
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(["Flooding", "Shortest Path", "Gossip"])
    ax3.set_ylabel("Packets per Message (count)")
    ax3.set_title("Packet Overhead")
    ax3.grid(True, linestyle=":", alpha=0.5, axis="y")

    plt.suptitle("Routing Comparison: Flooding vs Shortest-Path vs Gossip", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plot_path = os.path.join("results", "exp1_routing_comparison.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()

    print(f"Saved: {csv_path} and {plot_path}")
    return stats


# -------------------------------------------------------------
# Experiment 2: Scalability
# -------------------------------------------------------------
def run_experiment_2(trials: int = 20) -> Dict[int, dict]:
    print("\n[2/4] Running Experiment 2: Scalability (5, 10, 20, 50 nodes)...")
    node_counts = [5, 10, 20, 50]
    results = []

    for n_nodes in node_counts:
        # scale deployment area with node count to maintain realistic density
        side = math.sqrt(n_nodes) * 16.0
        for trial in range(trials):
            seed = 200 + trial
            random.seed(seed)
            channel = WirelessChannel(n=2.5, sigma=1.5)

            # generate node coordinates
            node_positions = {
                f"N{i}": (random.uniform(5, side), random.uniform(5, side))
                for i in range(n_nodes)
            }

            temp_net = Network(transmission_range=32.0, channel=channel, seed=seed)
            for name, (x, y) in node_positions.items():
                temp_net.add_node(name, x, y)
            temp_net.build_links()
            src, dst, hops = get_connected_pair(temp_net)
            if not src or not dst:
                continue

            for rtype in ["flooding", "shortest"]:
                net = Network(transmission_range=32.0, channel=channel, default_router=rtype, seed=seed)
                for name, (x, y) in node_positions.items():
                    net.add_node(name, x, y, router_type=rtype)
                net.build_links()

                if rtype == "shortest":
                    # hello rounds scaled to network diameter
                    hello_rounds = max(4, int(math.sqrt(n_nodes)) + 2)
                    for _ in range(hello_rounds):
                        net.broadcast_hellos()
                        net.run()

                tx_before = net.total_transmissions
                net.send_message(src, dst, payload=f"scale-{n_nodes}-{trial}")
                net.run()

                tx_msg = net.total_transmissions - tx_before
                deliv_list = net.nodes[dst].router.delivered_messages
                delivered = 1 if any(m.payload == f"scale-{n_nodes}-{trial}" for m in deliv_list) else 0

                delay = 0
                for m in deliv_list:
                    if m.payload == f"scale-{n_nodes}-{trial}":
                        delay = max(1, len(m.path) - 1)
                        break

                results.append({
                    "nodes": n_nodes,
                    "trial": trial,
                    "seed": seed,
                    "router": rtype,
                    "delivered": delivered,
                    "delay_hops": delay if delivered else 0,
                    "packets_transmitted": tx_msg,
                })

    csv_path = os.path.join("results", "exp2_scalability.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["nodes", "trial", "seed", "router", "delivered", "delay_hops", "packets_transmitted"])
        writer.writeheader()
        writer.writerows(results)

    stats = {}
    for n_nodes in node_counts:
        stats[n_nodes] = {}
        for rtype in ["flooding", "shortest"]:
            subset = [r for r in results if r["nodes"] == n_nodes and r["router"] == rtype]
            pkts = [r["packets_transmitted"] for r in subset]
            delays = [r["delay_hops"] for r in subset if r["delivered"] == 1]
            stats[n_nodes][rtype] = {
                "packets_mean": np.mean(pkts) if pkts else 0.0,
                "packets_std": np.std(pkts) if pkts else 0.0,
                "delay_mean": np.mean(delays) if delays else 0.0,
                "delay_std": np.std(delays) if delays else 0.0,
            }

    # plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # packet overhead vs node count
    f_means = [stats[n]["flooding"]["packets_mean"] for n in node_counts]
    f_stds = [stats[n]["flooding"]["packets_std"] for n in node_counts]
    s_means = [stats[n]["shortest"]["packets_mean"] for n in node_counts]
    s_stds = [stats[n]["shortest"]["packets_std"] for n in node_counts]

    ax1.errorbar(node_counts, f_means, yerr=f_stds, label="Flooding", color="#ef4444", marker="o", capsize=4)
    ax1.errorbar(node_counts, s_means, yerr=s_stds, label="Shortest Path", color="#0284c7", marker="s", capsize=4)
    ax1.set_xlabel("Number of Nodes")
    ax1.set_ylabel("Packets Transmitted per Message")
    ax1.set_title("Packet Overhead vs Network Size")
    ax1.grid(True, linestyle=":", alpha=0.5)
    ax1.legend()

    # delay vs node count
    f_delays = [stats[n]["flooding"]["delay_mean"] for n in node_counts]
    f_delays_std = [stats[n]["flooding"]["delay_std"] for n in node_counts]
    s_delays = [stats[n]["shortest"]["delay_mean"] for n in node_counts]
    s_delays_std = [stats[n]["shortest"]["delay_std"] for n in node_counts]

    ax2.errorbar(node_counts, f_delays, yerr=f_delays_std, label="Flooding", color="#ef4444", marker="o", capsize=4)
    ax2.errorbar(node_counts, s_delays, yerr=s_delays_std, label="Shortest Path", color="#0284c7", marker="s", capsize=4)
    ax2.set_xlabel("Number of Nodes")
    ax2.set_ylabel("Average Delay (hops)")
    ax2.set_title("Delivery Delay vs Network Size")
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.legend()

    plt.suptitle("Scalability: Packet Overhead and Delay up to 50 Nodes", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plot_path = os.path.join("results", "exp2_scalability.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()

    print(f"Saved: {csv_path} and {plot_path}")
    return stats


# -------------------------------------------------------------
# Experiment 3: Distance and Path Loss
# -------------------------------------------------------------
def run_experiment_3(trials: int = 20) -> Dict[Tuple[float, float], dict]:
    print("\n[3/4] Running Experiment 3: Distance and Path Loss (n = 2, 3, 4)...")
    spacings = [10.0, 20.0, 30.0, 40.0, 50.0]
    exponents = [2.0, 3.0, 4.0]
    results = []

    for n in exponents:
        for dist in spacings:
            for trial in range(trials):
                seed = 300 + trial
                channel = WirelessChannel(n=n, sigma=3.0)
                # 3-hop linear chain: N0 -(dist)-> N1 -(dist)-> N2 -(dist)-> N3
                net = Network(transmission_range=dist + 5.0, channel=channel, default_router="flooding", seed=seed)
                for i in range(4):
                    net.add_node(f"N{i}", i * dist, 0.0)
                net.build_links()

                # send 5 test messages
                deliv_count = 0
                tx_total = 0
                success_total = 0

                for m_idx in range(5):
                    tx_b = net.total_transmissions
                    succ_b = net.successful_transmissions
                    net.send_message("N0", "N3", payload=f"pl-{m_idx}")
                    net.run()
                    tx_total += (net.total_transmissions - tx_b)
                    success_total += (net.successful_transmissions - succ_b)
                    if any(m.payload == f"pl-{m_idx}" for m in net.nodes["N3"].router.delivered_messages):
                        deliv_count += 1

                link_success = (success_total / tx_total * 100) if tx_total > 0 else 0.0
                delivery_rate = (deliv_count / 5.0) * 100

                results.append({
                    "n": n,
                    "spacing_m": dist,
                    "trial": trial,
                    "seed": seed,
                    "link_success_pct": link_success,
                    "delivery_rate_pct": delivery_rate,
                })

    csv_path = os.path.join("results", "exp3_path_loss.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["n", "spacing_m", "trial", "seed", "link_success_pct", "delivery_rate_pct"])
        writer.writeheader()
        writer.writerows(results)

    stats = {}
    for n in exponents:
        for dist in spacings:
            subset = [r for r in results if r["n"] == n and r["spacing_m"] == dist]
            link_rates = [r["link_success_pct"] for r in subset]
            deliv_rates = [r["delivery_rate_pct"] for r in subset]
            stats[(n, dist)] = {
                "link_mean": np.mean(link_rates),
                "link_std": np.std(link_rates),
                "deliv_mean": np.mean(deliv_rates),
                "deliv_std": np.std(deliv_rates),
            }

    # plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    colors = {2.0: "#22c55e", 3.0: "#0284c7", 4.0: "#ef4444"}

    for n in exponents:
        link_means = [stats[(n, d)]["link_mean"] for d in spacings]
        link_stds = [stats[(n, d)]["link_std"] for d in spacings]
        ax1.errorbar(spacings, link_means, yerr=link_stds, label=f"n = {int(n)}", color=colors[n], marker="o", capsize=4)

        deliv_means = [stats[(n, d)]["deliv_mean"] for d in spacings]
        deliv_stds = [stats[(n, d)]["deliv_std"] for d in spacings]
        ax2.errorbar(spacings, deliv_means, yerr=deliv_stds, label=f"n = {int(n)}", color=colors[n], marker="s", capsize=4)

    ax1.set_xlabel("Node Spacing (m)")
    ax1.set_ylabel("Link Success Rate (%)")
    ax1.set_title("Link Success Rate vs Distance")
    ax1.set_ylim(-5, 105)
    ax1.grid(True, linestyle=":", alpha=0.5)
    ax1.legend()

    ax2.set_xlabel("Node Spacing (m)")
    ax2.set_ylabel("End-to-End Delivery Rate (%)")
    ax2.set_title("End-to-End Delivery vs Distance")
    ax2.set_ylim(-5, 105)
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.legend()

    plt.suptitle("Distance and Path Loss: Impact of Exponent n on Link and Delivery Success", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plot_path = os.path.join("results", "exp3_path_loss.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()

    print(f"Saved: {csv_path} and {plot_path}")
    return stats


# -------------------------------------------------------------
# Experiment 4: Failure and Fault Recovery
# -------------------------------------------------------------
def run_experiment_4(trials: int = 20) -> Dict[int, dict]:
    print("\n[4/4] Running Experiment 4: Failure and Fault Recovery (switch off 1, 2, 3 nodes)...")
    fail_counts = [1, 2, 3]
    results = []

    for k_fail in fail_counts:
        for trial in range(trials):
            seed = 400 + trial
            random.seed(seed)
            channel = WirelessChannel(n=2.5, sigma=1.0)
            net = Network(transmission_range=42.0, channel=channel, default_router="shortest", seed=seed)

            # grid topology with rich redundancy between (0, 0) and (90, 60)
            # 3 rows of 4 nodes: 12 nodes total
            node_names = []
            for row in range(3):
                for col in range(4):
                    name = f"N_{row}_{col}"
                    x = col * 30.0 + random.uniform(-2, 2)
                    y = row * 30.0 + random.uniform(-2, 2)
                    net.add_node(name, x, y)
                    node_names.append(name)
            net.build_links()

            src = "N_0_0"
            dst = "N_2_3"

            # initial hello convergence
            for _ in range(4):
                net.broadcast_hellos()
                net.run()

            # initial message
            net.send_message(src, dst, payload=f"init-{trial}")
            net.run()

            deliv_init = [m for m in net.nodes[dst].router.delivered_messages if m.payload == f"init-{trial}"]
            if not deliv_init:
                continue
            path = deliv_init[-1].path

            # identify intermediate relay nodes on the active path
            relays = [node for node in path if node != src and node != dst]
            if not relays:
                continue

            # send second message
            net.send_message(src, dst, payload=f"fail-{trial}")
            net.step()

            # kill k relay nodes mid-delivery
            t_fail = net.time_step
            nodes_to_kill = relays[:k_fail]
            for n_kill in nodes_to_kill:
                net.kill_node(n_kill)

            net.run(max_steps=2)

            # hello timeouts: 3 missed hellos
            for _ in range(3):
                net.broadcast_hellos()
                net.run()

            # attempt delivery via alternative route
            net.send_message(src, dst, payload=f"rerouted-{trial}")
            net.run()

            t_deliv = net.time_step
            deliv_rerouted = [m for m in net.nodes[dst].router.delivered_messages if m.payload == f"rerouted-{trial}"]
            recovered = 1 if deliv_rerouted else 0
            recovery_time = (t_deliv - t_fail) if recovered else 0

            results.append({
                "failed_nodes": k_fail,
                "trial": trial,
                "seed": seed,
                "recovered": recovered,
                "recovery_time_steps": recovery_time,
                "delivery_rate_pct": 100.0 if recovered else 0.0,
            })

    csv_path = os.path.join("results", "exp4_failure.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["failed_nodes", "trial", "seed", "recovered", "recovery_time_steps", "delivery_rate_pct"])
        writer.writeheader()
        writer.writerows(results)

    stats = {}
    for k_fail in fail_counts:
        subset = [r for r in results if r["failed_nodes"] == k_fail]
        recov_times = [r["recovery_time_steps"] for r in subset if r["recovered"] == 1]
        deliv_rates = [r["delivery_rate_pct"] for r in subset]
        stats[k_fail] = {
            "recovery_time_mean": np.mean(recov_times) if recov_times else 0.0,
            "recovery_time_std": np.std(recov_times) if recov_times else 0.0,
            "delivery_rate_mean": np.mean(deliv_rates),
            "delivery_rate_std": np.std(deliv_rates),
        }

    # plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    x_pos = np.array(fail_counts)

    # recovery time
    rec_means = [stats[k]["recovery_time_mean"] for k in fail_counts]
    rec_stds = [stats[k]["recovery_time_std"] for k in fail_counts]
    ax1.bar(x_pos, rec_means, yerr=rec_stds, capsize=4, color="#0284c7", alpha=0.85, edgecolor="#334155", width=0.5)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(["1 Node", "2 Nodes", "3 Nodes"])
    ax1.set_xlabel("Number of Failed Relay Nodes")
    ax1.set_ylabel("Recovery Time (time steps)")
    ax1.set_title("Recovery Time After Failure")
    ax1.grid(True, linestyle=":", alpha=0.5, axis="y")

    # delivery rate
    deliv_means = [stats[k]["delivery_rate_mean"] for k in fail_counts]
    deliv_stds = [stats[k]["delivery_rate_std"] for k in fail_counts]
    ax2.bar(x_pos, deliv_means, yerr=deliv_stds, capsize=4, color="#10b981", alpha=0.85, edgecolor="#334155", width=0.5)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(["1 Node", "2 Nodes", "3 Nodes"])
    ax2.set_xlabel("Number of Failed Relay Nodes")
    ax2.set_ylabel("Delivery Rate (%)")
    ax2.set_title("Delivery Rate After Failure")
    ax2.set_ylim(0, 110)
    ax2.grid(True, linestyle=":", alpha=0.5, axis="y")

    plt.suptitle("Fault Recovery: Rerouting and Recovery Time under Node Failures", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plot_path = os.path.join("results", "exp4_failure.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()

    print(f"Saved: {csv_path} and {plot_path}")
    return stats


# -------------------------------------------------------------
# Summary Table
# -------------------------------------------------------------
def print_summary_table(stats1, stats2, stats3, stats4):
    print("\n" + "=" * 78)
    print("                      MESHage EXPERIMENT SUMMARY TABLE")
    print("=" * 78)

    print("\n1. ROUTING COMPARISON (15 nodes):")
    print(f"{'Protocol':<16} | {'Delivery Rate (%)':<20} | {'Delay (hops)':<18} | {'Packets/Msg':<16}")
    print("-" * 78)
    for r in ["flooding", "shortest", "gossip"]:
        s = stats1[r]
        deliv = f"{s['delivery_rate_mean']:.1f} +/- {s['delivery_rate_std']:.1f}%"
        delay = f"{s['delay_mean']:.2f} +/- {s['delay_std']:.2f}"
        pkts = f"{s['packets_mean']:.1f} +/- {s['packets_std']:.1f}"
        print(f"{r.capitalize():<16} | {deliv:<20} | {delay:<18} | {pkts:<16}")

    print("\n2. SCALABILITY (Flooding vs Shortest Path):")
    print(f"{'Nodes':<8} | {'Flooding Packets':<20} | {'Shortest Packets':<20} | {'Delay (hops)':<16}")
    print("-" * 78)
    for n in [5, 10, 20, 50]:
        s_f = stats2[n]["flooding"]
        s_s = stats2[n]["shortest"]
        f_p = f"{s_f['packets_mean']:.1f} +/- {s_f['packets_std']:.1f}"
        s_p = f"{s_s['packets_mean']:.1f} +/- {s_s['packets_std']:.1f}"
        delay = f"{s_s['delay_mean']:.2f} +/- {s_s['delay_std']:.2f}"
        print(f"{n:<8} | {f_p:<20} | {s_p:<20} | {delay:<16}")

    print("\n3. DISTANCE AND PATH LOSS:")
    print(f"{'Path Exponent n':<18} | {'Spacing (m)':<14} | {'Link Success (%)':<20} | {'Delivery Rate (%)':<18}")
    print("-" * 78)
    for n in [2.0, 3.0, 4.0]:
        for d in [10.0, 30.0, 50.0]:
            s = stats3[(n, d)]
            link = f"{s['link_mean']:.1f} +/- {s['link_std']:.1f}%"
            deliv = f"{s['deliv_mean']:.1f} +/- {s['deliv_std']:.1f}%"
            print(f"n = {int(n):<14} | {d:<14.0f} | {link:<20} | {deliv:<18}")

    print("\n4. FAULT RECOVERY:")
    print(f"{'Failed Nodes':<16} | {'Recovery Time (steps)':<24} | {'Delivery Rate (%)':<20}")
    print("-" * 78)
    for k in [1, 2, 3]:
        s = stats4[k]
        rec = f"{s['recovery_time_mean']:.1f} +/- {s['recovery_time_std']:.1f}"
        deliv = f"{s['delivery_rate_mean']:.1f} +/- {s['delivery_rate_std']:.1f}%"
        print(f"{k} node(s) failed  | {rec:<24} | {deliv:<20}")
    print("=" * 78 + "\n")


def main():
    setup_style()
    os.makedirs("results", exist_ok=True)
    t_start = time.time()

    stats1 = run_experiment_1(trials=20)
    stats2 = run_experiment_2(trials=20)
    stats3 = run_experiment_3(trials=20)
    stats4 = run_experiment_4(trials=20)

    print_summary_table(stats1, stats2, stats3, stats4)
    print(f"All experiments completed in {time.time() - t_start:.2f} seconds.")


if __name__ == "__main__":
    main()
