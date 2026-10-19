"""
demo script for flooding routing in meshage
"""
import os
import random
import sys

# ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import matplotlib.pyplot as plt
import networkx as nx
from sim.network import Network


def main():
    # use seed for repeatable connected topology
    seed = 1
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        seed = int(sys.argv[1])
    random.seed(seed)

    # 1. create 10 random nodes
    net = Network(transmission_range=32.0)
    for i in range(10):
        net.add_node(f"N{i}", random.uniform(10, 90), random.uniform(10, 90))
    net.build_links()

    first_node = "N0"
    last_node = "N9"

    # 2. send one message from the first to the last
    print(f"Sending message from {first_node} to {last_node}...")
    net.send_message(src=first_node, dst=last_node, payload="hello meshage")
    net.run()

    # check delivered message at destination
    delivered = net.nodes[last_node].router.delivered_messages
    if not delivered:
        print(f"Message did not reach {last_node}")
        return

    msg = delivered[0]
    path = msg.path
    hop_count = len(path) - 1

    # 3. print path and hop count
    print("Message reached destination successfully!")
    print(f"Path: {' -> '.join(path)}")
    print(f"Hop count: {hop_count}")

    # 4. draw the graph with networkx and matplotlib
    g = nx.Graph()
    pos = {}
    for name, node in net.nodes.items():
        g.add_node(name)
        pos[name] = (node.x, node.y)
        for nbr in node.neighbors:
            g.add_edge(name, nbr)

    path_edges = list(zip(path[:-1], path[1:]))

    plt.figure(figsize=(9, 7))

    # draw background network links
    nx.draw_networkx_edges(
        g,
        pos,
        edge_color="#cbd5e1",
        width=1.5,
        style="solid",
    )

    # draw highlighted path edges
    nx.draw_networkx_edges(
        g,
        pos,
        edgelist=path_edges,
        edge_color="#0284c7",
        width=3.5,
    )

    # color nodes based on role in delivery
    node_colors = []
    for node_name in g.nodes():
        if node_name == first_node:
            node_colors.append("#22c55e")  # source: green
        elif node_name == last_node:
            node_colors.append("#ef4444")  # destination: red
        elif node_name in path:
            node_colors.append("#38bdf8")  # on path: sky blue
        else:
            node_colors.append("#e2e8f0")  # other: light gray

    nx.draw_networkx_nodes(
        g,
        pos,
        node_color=node_colors,
        node_size=700,
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
        f"MESHage Flooding: {' -> '.join(path)} ({hop_count} hops)",
        fontsize=13,
        fontweight="bold",
        pad=15,
    )
    plt.axis("off")
    plt.tight_layout()

    # save plot to results
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "demo_path.png")
    plt.savefig(out_path, dpi=150)
    print(f"Graph saved to {out_path}")

    # show plot if display available and not explicitly disabled
    if "--no-show" not in sys.argv:
        try:
            plt.show()
        except Exception:
            pass


if __name__ == "__main__":
    main()
