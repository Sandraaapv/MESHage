"""
self-healing demonstration: node failure mid-delivery and automatic rerouting
"""
import os
import sys

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib.pyplot as plt
import networkx as nx
from sim.channel import WirelessChannel
from sim.network import Network


def main():
    print("Setting up mesh network with redundant paths...")
    # use line of sight channel so links are stable for path failure demo
    channel = WirelessChannel(n=2.5, sigma=0.0)
    net = Network(transmission_range=40.0, channel=channel, default_router="shortest", seed=42)

    # create topology with two alternate paths between N0 and N4:
    # Path A: N0 -> N1 -> N2 -> N4
    # Path B: N0 -> N3 -> N5 -> N4
    pos = {
        "N0": (10, 50),
        "N1": (40, 75),
        "N2": (70, 75),
        "N3": (40, 25),
        "N5": (70, 25),
        "N4": (95, 50),
    }
    for name, (x, y) in pos.items():
        net.add_node(name, x, y)

    net.build_links()

    # exchange initial hellos so all nodes learn network topology
    print("Exchanging initial hello messages...")
    for _ in range(4):
        net.broadcast_hellos()
        net.run()

    # step 1: send first message along primary path
    src = "N0"
    dst = "N4"
    print(f"\n1. Sending initial message from {src} to {dst}...")
    net.send_message(src, dst, payload="packet 1")
    net.run()

    deliv_node = net.nodes[dst]
    if deliv_node.router.delivered_messages:
        initial_path = deliv_node.router.delivered_messages[-1].path
        print(f"Message delivered via primary path: {' -> '.join(initial_path)}")
    else:
        print("Initial message failed to deliver.")
        return

    # step 2: send second message and kill relay node N1 mid-delivery
    print(f"\n2. Sending packet 2 from {src} to {dst}...")
    msg2 = net.send_message(src, dst, payload="packet 2")

    # message moves one hop (N0 to N1)
    net.step()

    # kill relay node N1 mid-delivery
    failed_node = "N1"
    failure_step = net.time_step
    print(f"Killing relay node {failed_node} mid-delivery at step {failure_step}...")
    net.kill_node(failed_node)

    # step network: transmission to dead node fails
    net.run(max_steps=2)

    # step 3: self-healing via hello timeouts
    print("Waiting for neighbor hello timeouts and route recomputation...")
    # advance hellos until N0 marks N1 as DOWN (threshold = 3 missed hellos)
    for _ in range(3):
        net.broadcast_hellos()
        net.run()

    new_next_hop = net.nodes[src].router.compute_route(dst)
    print(f"Route recomputed at {src}: new next hop is {new_next_hop}")

    # step 4: retransmit packet through healed path
    print(f"Resending packet from {src} to {dst} through healed path...")
    net.send_message(src, dst, payload="packet 2 (rerouted)")
    net.run()

    delivery_step = net.time_step
    recovery_time = delivery_step - failure_step

    # check delivered packet on destination
    rerouted_msgs = [
        m for m in net.nodes[dst].router.delivered_messages
        if "rerouted" in m.payload
    ]

    if rerouted_msgs:
        healed_path = rerouted_msgs[-1].path
        print("\n=== FAULT RECOVERY SUCCESSFUL ===")
        print(f"Original path:  {' -> '.join(initial_path)}")
        print(f"Failed node:    {failed_node}")
        print(f"Healed path:    {' -> '.join(healed_path)}")
        print(f"Failure step:   {failure_step}")
        print(f"Delivery step:  {delivery_step}")
        print(f"Recovery time:  {recovery_time} steps")
    else:
        print("Rerouted message failed to deliver.")
        return

    # step 5: draw topology visualization
    g = nx.Graph()
    for name in pos:
        g.add_node(name)
    edges = [
        ("N0", "N1"), ("N1", "N2"), ("N2", "N4"),
        ("N0", "N3"), ("N3", "N5"), ("N5", "N4"),
    ]
    g.add_edges_from(edges)

    plt.figure(figsize=(9, 6))

    # draw background links
    nx.draw_networkx_edges(g, pos, edge_color="#cbd5e1", width=1.5)

    # draw failed path in dashed red
    failed_edges = list(zip(initial_path[:-1], initial_path[1:]))
    nx.draw_networkx_edges(
        g,
        pos,
        edgelist=failed_edges,
        edge_color="#f87171",
        width=2.0,
        style="dashed",
    )

    # draw healed path in bold blue
    healed_edges = list(zip(healed_path[:-1], healed_path[1:]))
    nx.draw_networkx_edges(
        g,
        pos,
        edgelist=healed_edges,
        edge_color="#0284c7",
        width=3.5,
    )

    # node colors
    node_colors = []
    for name in g.nodes():
        if name == failed_node:
            node_colors.append("#ef4444")  # failed: red
        elif name == src:
            node_colors.append("#22c55e")  # source: green
        elif name == dst:
            node_colors.append("#10b981")  # destination: emerald
        elif name in healed_path:
            node_colors.append("#38bdf8")  # on healed path: sky blue
        else:
            node_colors.append("#e2e8f0")  # inactive: gray

    nx.draw_networkx_nodes(
        g,
        pos,
        node_color=node_colors,
        node_size=800,
        edgecolors="#334155",
        linewidths=1.5,
    )

    nx.draw_networkx_labels(
        g,
        pos,
        font_size=11,
        font_weight="bold",
        font_color="#0f172a",
    )

    plt.title(
        f"MESHage Fault Recovery: Node {failed_node} Failed -> Rerouted via {' -> '.join(healed_path)}\n"
        f"Recovery Time: {recovery_time} steps",
        fontsize=12,
        fontweight="bold",
        pad=15,
    )
    plt.xlabel("X Position (m)", fontsize=11, fontweight="bold")
    plt.ylabel("Y Position (m)", fontsize=11, fontweight="bold")
    plt.grid(True, linestyle=":", alpha=0.5)
    plt.tight_layout()

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "demo_heal.png")
    plt.savefig(out_file, dpi=150)
    print(f"\nFault recovery graph saved to {out_file}")

    if "--no-show" not in sys.argv:
        try:
            plt.show()
        except Exception:
            pass


if __name__ == "__main__":
    main()
