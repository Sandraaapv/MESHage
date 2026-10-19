"""
python runner for local 3-node mesh test
starts node A (5001), B (5002), and C (5003) on localhost
sends message from A to C through relay B and verifies path A -> B -> C
"""
import os
import sys
import time

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from node.mesh_node import MeshNode


def main():
    print("=== MESHage Local 3-Node Test ===")
    print("Topology: A (port 5001) <---> B (port 5002) <---> C (port 5003)")
    print("Rules: A knows only B. B knows A and C. C knows only B.\n")

    # create three node instances
    node_c = MeshNode(name="C", port=5003, neighbors=[("127.0.0.1", 5002)], hello_interval=1.0)
    node_b = MeshNode(name="B", port=5002, neighbors=[("127.0.0.1", 5001), ("127.0.0.1", 5003)], hello_interval=1.0)
    node_a = MeshNode(name="A", port=5001, neighbors=[("127.0.0.1", 5002)], hello_interval=1.0)

    try:
        # start nodes
        node_c.start()
        node_b.start()
        node_a.start()

        print("\nWaiting for hello messages to discover neighbors...")
        time.sleep(2.5)

        # verify direct neighbors
        print(f"\n[Status] Node A active neighbors: {node_a.get_active_neighbor_names()}")
        print(f"[Status] Node B active neighbors: {node_b.get_active_neighbor_names()}")
        print(f"[Status] Node C active neighbors: {node_c.get_active_neighbor_names()}")

        # send message from Node A to Node C
        test_payload = "hello node C from node A"
        print(f"\n[Action] Typing message into Node A: send C '{test_payload}'...")
        node_a.send_chat(dst="C", payload=test_payload)

        # wait for multi-hop propagation
        time.sleep(1.5)

        # check delivered messages at Node C
        deliv_c = [m for m in node_c.messages if m["src"] == "A"]

        print("\n=== VERIFICATION RESULT ===")
        if deliv_c:
            delivered = deliv_c[-1]
            path_str = " -> ".join(delivered["path"])
            print(f"Message successfully arrived at Node C!")
            print(f"Payload:   '{delivered['payload']}'")
            print(f"Path:      {path_str}")
            print(f"Hop count: {len(delivered['path']) - 1}")

            assert delivered["path"] == ["A", "B", "C"], f"Expected ['A', 'B', 'C'], got {delivered['path']}"
            print("\nTest passed: multi-hop UDP delivery A -> B -> C verified!")
        else:
            print("Error: Message from A did not reach C!")
            sys.exit(1)

    finally:
        print("\nStopping all nodes...")
        node_a.stop()
        node_b.stop()
        node_c.stop()
        print("All nodes stopped cleanly.")


if __name__ == "__main__":
    main()
