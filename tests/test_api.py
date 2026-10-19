"""
unit and integration tests for node/api.py
"""
import json
import os
import sys
import time
import unittest

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from node.api import create_app
from node.mesh_node import MeshNode


class TestNodeAPI(unittest.TestCase):
    def setUp(self):
        # mock node for API testing
        self.node = MeshNode(
            name="TestNode",
            port=6101,
            neighbors=[("127.0.0.1", 6102)],
            routing="flooding",
            hello_interval=1.0,
        )
        self.node.neighbor_table["NeighborB"] = {
            "status": "UP",
            "last_seen": time.time(),
            "addr": ("127.0.0.1", 6102),
        }
        self.app = create_app(self.node)
        self.client = self.app.test_client()

    def test_get_state(self):
        resp = self.client.get("/api/state")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["node_name"], "TestNode")
        self.assertEqual(data["routing_mode"], "flooding")
        self.assertIn("neighbors", data)
        self.assertEqual(len(data["neighbors"]), 1)
        self.assertEqual(data["neighbors"][0]["name"], "NeighborB")
        self.assertEqual(data["neighbors"][0]["status"], "UP")
        self.assertIn("counters", data)

    def test_post_send(self):
        resp = self.client.post(
            "/api/send",
            data=json.dumps({"dst": "NeighborB", "payload": "hello api test"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["src"], "TestNode")
        self.assertEqual(data["dst"], "NeighborB")
        self.assertEqual(data["payload"], "hello api test")

    def test_post_alert(self):
        resp = self.client.post(
            "/api/alert",
            data=json.dumps({"payload": "wildfire warning"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["dst"], "ALL")
        self.assertEqual(data["type"], "emergency")

    def test_get_messages(self):
        # send message first
        self.client.post(
            "/api/send",
            data=json.dumps({"dst": "NeighborB", "payload": "history test"}),
            content_type="application/json",
        )
        resp = self.client.get("/api/messages")
        self.assertEqual(resp.status_code, 200)
        history = resp.get_json()
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[-1]["payload"], "history test")

    def test_serve_static_root(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"MESHage", resp.data)


class TestMultiNodeAPIDelivery(unittest.TestCase):
    def test_api_multi_hop_delivery(self):
        # 3 live nodes over UDP with API: A <-> B <-> C
        node_c = MeshNode(name="C", port=6203, neighbors=[("127.0.0.1", 6202)], hello_interval=1.0)
        node_b = MeshNode(name="B", port=6202, neighbors=[("127.0.0.1", 6201), ("127.0.0.1", 6203)], hello_interval=1.0)
        node_a = MeshNode(name="A", port=6201, neighbors=[("127.0.0.1", 6202)], hello_interval=1.0)

        app_a = create_app(node_a)
        app_c = create_app(node_c)
        client_a = app_a.test_client()
        client_c = app_c.test_client()

        try:
            node_c.start()
            node_b.start()
            node_a.start()
            time.sleep(2.5)

            # send via Node A API to Node C
            resp = client_a.post(
                "/api/send",
                data=json.dumps({"dst": "C", "payload": "api message through mesh"}),
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)

            time.sleep(1.5)

            # check Node C API messages
            resp_c = client_c.get("/api/messages")
            self.assertEqual(resp_c.status_code, 200)
            messages_c = resp_c.get_json()
            delivered_from_a = [m for m in messages_c if m["src"] == "A"]

            self.assertTrue(len(delivered_from_a) >= 1)
            msg = delivered_from_a[-1]
            self.assertEqual(msg["payload"], "api message through mesh")
            self.assertEqual(msg["path"], ["A", "B", "C"])
            self.assertEqual(msg["delivery_status"], "delivered")

        finally:
            node_a.stop()
            node_b.stop()
            node_c.stop()


if __name__ == "__main__":
    unittest.main()
