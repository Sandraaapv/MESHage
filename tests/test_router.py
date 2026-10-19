"""
unit tests for core/router.py
covers flooding, shortest path, hello timeouts, fault recovery, and seen-id caching
"""
import json
import time
import unittest

from core.message import Message
from core.router import FloodingRouter, ShortestPathRouter, GossipRouter, SeenIdCache, dijkstra_next_hop


class TestSeenIdCache(unittest.TestCase):
    def test_cache_add_and_contains(self):
        cache = SeenIdCache(max_size=10, ttl=2.0)
        cache.add("msg-1")
        self.assertIn("msg-1", cache)
        self.assertNotIn("msg-2", cache)

    def test_cache_ttl_expiry(self):
        # short TTL of 0.15s
        cache = SeenIdCache(max_size=10, ttl=0.15)
        cache.add("msg-exp")
        self.assertIn("msg-exp", cache)

        # wait for expiration
        time.sleep(0.2)
        self.assertNotIn("msg-exp", cache)
        self.assertEqual(len(cache), 0)

    def test_cache_max_size_eviction(self):
        cache = SeenIdCache(max_size=3, ttl=100.0)
        cache.add("m1")
        cache.add("m2")
        cache.add("m3")
        self.assertEqual(len(cache), 3)

        # adding 4th item should evict oldest (m1)
        cache.add("m4")
        self.assertEqual(len(cache), 3)
        self.assertNotIn("m1", cache)
        self.assertIn("m2", cache)
        self.assertIn("m3", cache)
        self.assertIn("m4", cache)


class TestFloodingRouter(unittest.TestCase):
    def setUp(self):
        self.router_a = FloodingRouter(node_name="A", neighbors=["B", "C"])
        self.router_b = FloodingRouter(node_name="B", neighbors=["A", "D"])
        self.router_c = FloodingRouter(node_name="C", neighbors=["A", "D"])
        self.router_d = FloodingRouter(node_name="D", neighbors=["B", "C"])

    def test_unicast_delivery_at_destination(self):
        msg = Message(src="A", dst="D", payload="hello D", ttl=5)
        # Node A originates
        next_hops = self.router_a.handle(msg, from_node=None)
        self.assertEqual(set(next_hops), {"B", "C"})
        self.assertEqual(msg.path, ["A"])
        self.assertEqual(msg.ttl, 4)

        # Node B forwards to D (A is in path, so only D should be forwarded to)
        next_hops_b = self.router_b.handle(msg, from_node="A")
        self.assertEqual(next_hops_b, ["D"])
        self.assertEqual(msg.path, ["A", "B"])

        # Node D delivers
        next_hops_d = self.router_d.handle(msg, from_node="B")
        self.assertEqual(next_hops_d, [])
        self.assertEqual(len(self.router_d.delivered_messages), 1)
        self.assertEqual(self.router_d.delivered_messages[0].payload, "hello D")

    def test_broadcast_delivery(self):
        delivered = []
        router = FloodingRouter(node_name="X", neighbors=["Y", "Z"], on_deliver=lambda m: delivered.append(m))
        msg = Message(src="W", dst="ALL", payload="alert", ttl=3)
        next_hops = router.handle(msg, from_node="W")
        self.assertEqual(len(delivered), 1)
        self.assertEqual(set(next_hops), {"Y", "Z"})

    def test_loop_prevention_does_not_forward_to_path_nodes(self):
        # path is A -> B -> C; C neighbors are B and A
        router_c = FloodingRouter(node_name="C", neighbors=["B", "A", "E"])
        msg = Message(src="A", dst="Z", payload="test", ttl=4)
        msg.path = ["A", "B"]
        next_hops = router_c.handle(msg, from_node="B")
        # Should NOT forward back to B (from_node) or A (already in path)
        self.assertEqual(next_hops, ["E"])

    def test_duplicate_message_dropped_by_seen_ids(self):
        router = FloodingRouter(node_name="Node1", neighbors=["Node2"])
        msg = Message(src="Node0", dst="Node3", payload="data", ttl=4)

        # First reception
        hops1 = router.handle(msg, from_node="Node0")
        self.assertEqual(hops1, ["Node2"])

        # Second reception with same ID
        hops2 = router.handle(msg, from_node="Node0")
        self.assertEqual(hops2, [])

    def test_ttl_zero_drops_packet(self):
        router = FloodingRouter(node_name="M", neighbors=["N"])
        msg = Message(src="L", dst="O", payload="dead packet", ttl=0)
        next_hops = router.handle(msg, from_node="L")
        self.assertEqual(next_hops, [])
        self.assertEqual(len(router.delivered_messages), 0)


class TestShortestPathRouter(unittest.TestCase):
    def test_dijkstra_next_hop_simple(self):
        graph = {
            "A": {"B": 1.0, "C": 5.0},
            "B": {"A": 1.0, "C": 1.0},
            "C": {"A": 5.0, "B": 1.0},
        }
        # Shortest path A -> C is via B (cost 1+1=2 vs 5 direct)
        next_hop = dijkstra_next_hop(graph, "A", "C")
        self.assertEqual(next_hop, "B")

    def test_hello_exchange_and_topology_learning(self):
        r_a = ShortestPathRouter(node_name="A", neighbors=["B"])
        r_b = ShortestPathRouter(node_name="B", neighbors=["A", "C"])
        r_c = ShortestPathRouter(node_name="C", neighbors=["B"])

        # B creates hello and A processes it
        hello_b = r_b.create_hello()
        r_a.process_hello(hello_b)

        # C creates hello and B processes it
        hello_c = r_c.create_hello()
        r_b.process_hello(hello_c)

        # B shares updated link state with A
        hello_b2 = r_b.create_hello()
        r_a.process_hello(hello_b2)

        # A should now compute route to C via B
        route_to_c = r_a.compute_route("C")
        self.assertEqual(route_to_c, "B")

    def test_unicast_packet_routing(self):
        r_a = ShortestPathRouter(node_name="A", neighbors=["B"])
        r_b = ShortestPathRouter(node_name="B", neighbors=["A", "C"])

        # Populate link state manually
        r_a.neighbor_table["B"] = {"status": "UP", "missed_hellos": 0, "cost": 1.0}
        r_a.link_state_map["A"] = {"B": 1.0}
        r_a.link_state_map["B"] = {"A": 1.0, "C": 1.0}

        msg = Message(src="A", dst="C", payload="route test", ttl=5)
        next_hops = r_a.handle(msg, from_node=None)
        self.assertEqual(next_hops, ["B"])
        self.assertEqual(msg.path, ["A"])


class TestHelloTimeoutAndFaultRecovery(unittest.TestCase):
    def test_neighbor_timeout_after_missed_hellos(self):
        router = ShortestPathRouter(node_name="A", neighbors=["B"], missed_threshold=3)
        # Establish B as neighbor
        router.neighbor_table["B"] = {"status": "UP", "missed_hellos": 0, "cost": 1.0}
        router.link_state_map["A"] = {"B": 1.0}
        router.link_state_map["B"] = {"A": 1.0}

        # Tick 1: missed_hellos = 1 (still UP)
        downed = router.tick()
        self.assertEqual(downed, [])
        self.assertEqual(router.neighbor_table["B"]["status"], "UP")

        # Tick 2: missed_hellos = 2 (still UP)
        downed = router.tick()
        self.assertEqual(downed, [])
        self.assertEqual(router.neighbor_table["B"]["status"], "UP")

        # Tick 3: missed_hellos = 3 (marked DOWN)
        downed = router.tick()
        self.assertEqual(downed, ["B"])
        self.assertEqual(router.neighbor_table["B"]["status"], "DOWN")
        # Link removed from link_state_map
        self.assertNotIn("B", router.link_state_map.get("A", {}))

    def test_automatic_rerouting_upon_node_failure(self):
        # Topology:
        # Path 1: A <-> B <-> D
        # Path 2: A <-> C <-> D
        r_a = ShortestPathRouter(node_name="A", neighbors=["B", "C"], missed_threshold=2)

        # Setup initial neighbor table and link state: Path via B has lower cost (1.0 vs 3.0)
        r_a.neighbor_table["B"] = {"status": "UP", "missed_hellos": 0, "cost": 1.0}
        r_a.neighbor_table["C"] = {"status": "UP", "missed_hellos": 0, "cost": 3.0}
        r_a.link_state_map["A"] = {"B": 1.0, "C": 3.0}
        r_a.link_state_map["B"] = {"A": 1.0, "D": 1.0}
        r_a.link_state_map["C"] = {"A": 3.0, "D": 1.0}
        r_a.link_state_map["D"] = {"B": 1.0, "C": 1.0}

        # Initial best route to D is via B (total cost 2.0 vs 4.0 via C)
        self.assertEqual(r_a.compute_route("D"), "B")

        # Simulate B failing: missed hellos exceed threshold
        r_a.neighbor_table["B"]["missed_hellos"] = 2
        r_a.tick()
        self.assertEqual(r_a.neighbor_table["B"]["status"], "DOWN")

        # Route to D should automatically recompute through C!
        new_route = r_a.compute_route("D")
        self.assertEqual(new_route, "C")

    def test_neighbor_revival(self):
        router = ShortestPathRouter(node_name="X", neighbors=["Y"], missed_threshold=2)
        router.neighbor_table["Y"] = {"status": "DOWN", "missed_hellos": 5, "cost": 1.0}

        # Receiving a hello from Y revives it
        hello_y = Message(
            src="Y",
            dst="ALL",
            payload=json.dumps({"node": "Y", "neighbors": ["X"], "links": {"Y": {"X": 1.0}}}),
            type="hello",
        )
        router.process_hello(hello_y)
        self.assertEqual(router.neighbor_table["Y"]["status"], "UP")
        self.assertEqual(router.neighbor_table["Y"]["missed_hellos"], 0)
        self.assertIn("Y", router.get_active_neighbors())


if __name__ == "__main__":
    unittest.main()
