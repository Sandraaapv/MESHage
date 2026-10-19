"""
MESHage simulation server with Server-Sent Events (SSE) stream and REST API.
Serves the live projector dashboard from ui/dashboard/ and streams real-time
network events, packet animations, link updates, and metrics.
"""

import copy
import json
import os
import queue
import random
import sys
import threading
import time
from typing import Any, Dict, List, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, Response, jsonify, request, send_from_directory
from core.message import Message
from sim.channel import WirelessChannel
from sim.network import Network

app = Flask(
    __name__,
    static_folder=os.path.join(PROJECT_ROOT, "ui", "dashboard"),
    static_url_path="",
)

# Global simulation state and event broadcast hub
clients_lock = threading.Lock()
sse_clients: List[queue.Queue] = []


def broadcast_event(event_type: str, data: Any):
    """Broadcast an SSE event to all connected web clients."""
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with clients_lock:
        stale = []
        for q in sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                stale.append(q)
        for s in stale:
            if s in sse_clients:
                sse_clients.remove(s)


class SimulationController:
    """Manages the network simulation lifecycle, metrics, and event log."""

    def __init__(self, node_count: int = 30, n_exponent: float = 3.0, routing_mode: str = "shortest"):
        self.lock = threading.RLock()
        self.node_count = node_count
        self.n_exponent = n_exponent
        self.routing_mode = routing_mode
        self.tx_range = 195.0
        self.channel = WirelessChannel(
            tx_power_dbm=14.0,
            pl_d0=40.0,
            n=n_exponent,
            sigma=3.0,
            sensitivity_dbm=-85.0,
        )
        self.net = Network(
            transmission_range=self.tx_range,
            channel=self.channel,
            default_router=self.routing_mode,
            seed=42,
        )

        # Performance metrics tracking
        self.messages_sent = 0
        self.messages_delivered = 0
        self.total_hops = 0
        self.total_transmissions = 0
        self.last_failure_time: Optional[float] = None
        self.recovery_times: List[float] = []
        self.last_recovery_time: float = 0.0

        # Event log (circular buffer)
        self.event_log: List[Dict[str, Any]] = []

        # History buffers for sparklines
        self.metric_history = {
            "delivery_rate": [100.0],
            "avg_delay": [1.0],
            "packets_per_msg": [1.0],
            "active_nodes": [node_count],
            "recovery_time": [0.0],
        }

        self._init_topology(node_count)

    def _init_topology(self, count: int):
        self.net = Network(
            transmission_range=self.tx_range,
            channel=self.channel,
            default_router=self.routing_mode,
            seed=42,
        )
        rng = random.Random(42)

        # Generate a balanced mesh across standard canvas dimensions (1100 x 620)
        # using Poisson disk / jittered grid to avoid excessive overlapping
        cols = int(round(count ** 0.5 * 1.35))
        rows = max(2, (count + cols - 1) // cols)
        dx = 940.0 / max(1, cols)
        dy = 480.0 / max(1, rows)

        idx = 0
        for r in range(rows):
            for c in range(cols):
                if idx >= count:
                    break
                x = 80.0 + c * dx + rng.uniform(-dx * 0.28, dx * 0.28)
                y = 70.0 + r * dy + rng.uniform(-dy * 0.28, dy * 0.28)
                self.net.add_node(f"N{idx}", round(x, 1), round(y, 1), router_type=self.routing_mode)
                idx += 1

        self.net.build_links()
        self._prime_hellos()
        self.log_event("PARAM", f"Initialized mesh with {count} nodes ({self.routing_mode.upper()} router, n={self.n_exponent})")

    def _prime_hellos(self):
        """Exchange initial hellos so ShortestPathRouter builds its topology."""
        if self.routing_mode == "shortest":
            for _ in range(4):
                self.net.broadcast_hellos()
                self.net.run(max_steps=5)

    def log_event(self, event_type: str, message: str, meta: Optional[Dict[str, Any]] = None):
        """Record an event in the log buffer and broadcast to clients."""
        item = {
            "id": len(self.event_log) + 1,
            "type": event_type,
            "message": message,
            "time": time.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "meta": meta or {},
        }
        self.event_log.append(item)
        if len(self.event_log) > 200:
            self.event_log.pop(0)
        broadcast_event("event_log", item)

    def get_state(self) -> Dict[str, Any]:
        """Return the complete snapshot of the network state."""
        with self.lock:
            nodes_data = []
            alive_count = 0
            for name, node in self.net.nodes.items():
                if node.is_alive:
                    alive_count += 1
                nodes_data.append({
                    "name": name,
                    "x": node.x,
                    "y": node.y,
                    "alive": node.is_alive,
                    "neighbors": list(node.neighbors),
                })

            links_data = []
            seen_pairs = set()
            for name, node in self.net.nodes.items():
                for nbr in node.neighbors:
                    pair_key = tuple(sorted([name, nbr]))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    dist = self.net.distance(name, nbr)
                    nbr_node = self.net.nodes.get(nbr)
                    is_down = not (node.is_alive and nbr_node and nbr_node.is_alive)
                    p_succ = self.channel.packet_success_from_distance(dist, shadowing=False) if not is_down else 0.0

                    links_data.append({
                        "source": name,
                        "target": nbr,
                        "distance": round(dist, 1),
                        "success_prob": round(p_succ, 3),
                        "down": is_down,
                    })

            # Calculate live metrics
            deliv_rate = (self.messages_delivered / self.messages_sent * 100.0) if self.messages_sent > 0 else 100.0
            avg_delay = (self.total_hops / self.messages_delivered) if self.messages_delivered > 0 else 1.0
            pkts_per_msg = (self.total_transmissions / self.messages_delivered) if self.messages_delivered > 0 else 1.0

            return {
                "nodes": nodes_data,
                "links": links_data,
                "config": {
                    "node_count": len(self.net.nodes),
                    "n_exponent": round(self.n_exponent, 2),
                    "routing_mode": self.routing_mode,
                    "tx_range": self.tx_range,
                },
                "metrics": {
                    "delivery_rate": round(deliv_rate, 1),
                    "avg_delay": round(avg_delay, 2),
                    "packets_per_msg": round(pkts_per_msg, 2),
                    "active_nodes": alive_count,
                    "total_nodes": len(self.net.nodes),
                    "recovery_time": round(self.last_recovery_time, 2),
                },
                "metric_history": self.metric_history,
                "recent_events": self.event_log[-30:],
            }

    def _update_metrics_history(self):
        state = self.get_state()
        m = state["metrics"]
        for key in ["delivery_rate", "avg_delay", "packets_per_msg", "active_nodes", "recovery_time"]:
            buf = self.metric_history[key]
            buf.append(m[key])
            if len(buf) > 40:
                buf.pop(0)
        broadcast_event("metrics_updated", {
            "metrics": m,
            "metric_history": self.metric_history,
        })

    def move_node(self, name: str, x: float, y: float):
        with self.lock:
            if name in self.net.nodes:
                self.net.nodes[name].x = x
                self.net.nodes[name].y = y
                self.net.build_links()
                self._prime_hellos()
                broadcast_event("node_moved", {"name": name, "x": x, "y": y})
                broadcast_event("topology_updated", self.get_state())

    def toggle_node(self, name: str) -> bool:
        with self.lock:
            if name not in self.net.nodes:
                return False
            node = self.net.nodes[name]
            was_alive = node.is_alive
            new_alive = not was_alive
            if new_alive:
                self.net.revive_node(name)
                self.log_event("NODE", f"Node {name} revived and rejoined mesh", {"node": name, "alive": True})
            else:
                self.net.kill_node(name)
                self.last_failure_time = time.time()
                self.log_event("NODE", f"Node {name} failed / killed! Monitoring recovery...", {"node": name, "alive": False})

            self.net.build_links()
            self._prime_hellos()
            self._update_metrics_history()
            broadcast_event("node_toggled", {"name": name, "alive": new_alive})
            broadcast_event("topology_updated", self.get_state())
            return new_alive

    def kill_random_node(self) -> Optional[str]:
        with self.lock:
            alive = [n for n, node in self.net.nodes.items() if node.is_alive]
            if not alive:
                return None
            target = random.choice(alive)
            self.net.kill_node(target)
            self.last_failure_time = time.time()
            self.log_event("NODE", f"Random node failure: {target} is DOWN", {"node": target, "alive": False})
            self.net.build_links()
            self._prime_hellos()
            self._update_metrics_history()
            broadcast_event("node_toggled", {"name": target, "alive": False})
            broadcast_event("topology_updated", self.get_state())
            return target

    def set_path_loss_exponent(self, n: float):
        with self.lock:
            self.n_exponent = max(2.0, min(5.0, float(n)))
            self.channel.n = self.n_exponent
            self.net.build_links()
            self._prime_hellos()
            env = "Free Space" if self.n_exponent < 2.5 else "Suburban" if self.n_exponent < 3.2 else "Urban" if self.n_exponent < 4.0 else "High Obstruction"
            self.log_event("PARAM", f"Path-loss exponent n updated to {self.n_exponent:.1f} ({env})")
            broadcast_event("param_updated", {"n_exponent": self.n_exponent, "env": env})
            broadcast_event("topology_updated", self.get_state())

    def set_routing_mode(self, mode: str):
        with self.lock:
            if mode not in ["flooding", "shortest", "gossip"]:
                return
            self.routing_mode = mode
            self.net.default_router = mode
            for node in self.net.nodes.values():
                if mode == "shortest":
                    from core.router import ShortestPathRouter
                    node.router = ShortestPathRouter(node_name=node.name, neighbors=lambda n=node: n.neighbors)
                elif mode == "gossip":
                    from core.router import GossipRouter
                    node.router = GossipRouter(node_name=node.name, neighbors=lambda n=node: n.neighbors, p=0.6)
                else:
                    from core.router import FloodingRouter
                    node.router = FloodingRouter(node_name=node.name, neighbors=lambda n=node: n.neighbors)
            self.net.build_links()
            self._prime_hellos()
            self.log_event("PARAM", f"Routing mode changed to {mode.upper()}")
            broadcast_event("routing_mode_changed", {"routing_mode": mode})
            broadcast_event("topology_updated", self.get_state())

    def reset_network(self, count: Optional[int] = None):
        with self.lock:
            if count:
                self.node_count = count
            self.messages_sent = 0
            self.messages_delivered = 0
            self.total_hops = 0
            self.total_transmissions = 0
            self.last_failure_time = None
            self.last_recovery_time = 0.0
            self._init_topology(self.node_count)
            self._update_metrics_history()
            broadcast_event("topology_updated", self.get_state())

    def send_message(self, src: str, dst: str, payload: str = "Packet", msg_type: str = "chat") -> Dict[str, Any]:
        """Dispatch a message through the network and capture its multi-hop propagation."""
        with self.lock:
            if src not in self.net.nodes or dst not in self.net.nodes:
                return {"error": "Invalid source or destination"}
            if not self.net.nodes[src].is_alive:
                self.log_event("DROP", f"Cannot send from dead node {src}", {"src": src, "dst": dst})
                return {"error": f"Source {src} is dead"}

            self.messages_sent += 1
            start_time = time.time()
            msg = self.net.send_message(src=src, dst=dst, payload=payload, msg_type=msg_type)
            if not msg:
                return {"error": "Failed to inject message"}

            hop_steps: List[List[Dict[str, Any]]] = []
            transmissions_before = self.net.total_transmissions
            max_steps = 25
            step_count = 0

            # Step through network propagation hop-by-hop
            while self.net.has_active_messages() and step_count < max_steps:
                batch_in_flight = list(self.net.in_flight)
                current_hops = []
                for target_node, m, from_node in batch_in_flight:
                    if from_node:
                        current_hops.append({
                            "from": from_node,
                            "to": target_node,
                            "msg_id": m.id,
                            "type": m.type,
                            "path_so_far": list(m.path),
                        })
                if current_hops:
                    hop_steps.append(current_hops)

                self.net.step()
                step_count += 1

            new_transmissions = self.net.total_transmissions - transmissions_before
            self.total_transmissions += new_transmissions

            # Check if reached destination
            target_node = self.net.nodes[dst]
            delivered = False
            final_path = []

            for d_msg in target_node.router.delivered_messages:
                if d_msg.id == msg.id:
                    delivered = True
                    final_path = list(d_msg.path)
                    break

            if delivered:
                self.messages_delivered += 1
                hop_len = max(1, len(final_path) - 1)
                self.total_hops += hop_len

                # Check if this delivery constitutes recovery from a previous failure
                if self.last_failure_time is not None:
                    recovery_dur = round(time.time() - self.last_failure_time, 2)
                    self.last_recovery_time = max(0.4, recovery_dur)
                    self.recovery_times.append(self.last_recovery_time)
                    self.last_failure_time = None
                    self.log_event("ROUTE", f"Mesh healed! Alternate path verified in {self.last_recovery_time}s", {"recovery_time": self.last_recovery_time})

                self.log_event(
                    "DELIVERY",
                    f"Message delivered {src} -> {dst} ({hop_len} hops: {' -> '.join(final_path)})",
                    {"src": src, "dst": dst, "path": final_path, "hops": hop_len},
                )
            else:
                self.log_event(
                    "DROP",
                    f"Message dropped between {src} and {dst} (channel noise or broken link)",
                    {"src": src, "dst": dst},
                )

            self._update_metrics_history()

            result = {
                "msg_id": msg.id,
                "src": src,
                "dst": dst,
                "type": msg_type,
                "delivered": delivered,
                "final_path": final_path,
                "hops": len(final_path) - 1 if final_path else 0,
                "hop_steps": hop_steps,
                "transmissions": new_transmissions,
            }

            broadcast_event("message_result", result)
            return result

    def send_emergency_alert(self, payload: str = "EMERGENCY: EVACUATION ORDER") -> Dict[str, Any]:
        """Broadcast emergency alert to all nodes across the mesh."""
        with self.lock:
            alive_nodes = [n for n, node in self.net.nodes.items() if node.is_alive]
            if not alive_nodes:
                return {"error": "No alive nodes"}
            src = alive_nodes[0]

            self.messages_sent += 1
            transmissions_before = self.net.total_transmissions

            msg = Message(
                src=src,
                dst="ALL",
                payload=payload,
                type="alert",
                ttl=12,
            )

            # Injected into source node
            src_node = self.net.nodes[src]
            next_hops = src_node.router.handle(msg, from_node=None)
            for nxt in next_hops:
                self.net.in_flight.append((nxt, copy.deepcopy(msg), src))

            hop_steps: List[List[Dict[str, Any]]] = []
            max_steps = 30
            step_count = 0

            while self.net.has_active_messages() and step_count < max_steps:
                batch = list(self.net.in_flight)
                current_hops = []
                for target_node, m, from_node in batch:
                    if from_node:
                        current_hops.append({
                            "from": from_node,
                            "to": target_node,
                            "msg_id": m.id,
                            "type": "alert",
                        })
                if current_hops:
                    hop_steps.append(current_hops)
                self.net.step()
                step_count += 1

            new_transmissions = self.net.total_transmissions - transmissions_before
            self.total_transmissions += new_transmissions

            # Count nodes that received the alert
            reached = []
            for name, node in self.net.nodes.items():
                for m in node.router.delivered_messages:
                    if m.id == msg.id:
                        reached.append(name)
                        break

            self.messages_delivered += 1
            self.total_hops += 2

            self.log_event(
                "ALERT",
                f"EMERGENCY ALERT broadcast from {src} reached {len(reached)}/{len(alive_nodes)} active nodes!",
                {"reached_count": len(reached), "total_alive": len(alive_nodes)},
            )

            self._update_metrics_history()

            result = {
                "msg_id": msg.id,
                "src": src,
                "dst": "ALL",
                "type": "alert",
                "reached_nodes": reached,
                "hop_steps": hop_steps,
                "transmissions": new_transmissions,
            }
            broadcast_event("alert_broadcast", result)
            return result


sim_controller = SimulationController(node_count=30, n_exponent=3.0, routing_mode="shortest")


# =========================================================
# CORS & Static Routes
# =========================================================

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@app.route("/")
@app.route("/dashboard")
@app.route("/dashboard/")
def serve_dashboard():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)


# =========================================================
# SSE Stream Endpoint
# =========================================================

@app.route("/api/stream")
def sse_stream():
    """Server-Sent Events endpoint pushing live updates to the dashboard."""
    client_queue = queue.Queue(maxsize=100)
    with clients_lock:
        sse_clients.append(client_queue)

    def event_generator():
        # First send immediate snapshot state
        try:
            init_data = sim_controller.get_state()
            yield f"event: init\ndata: {json.dumps(init_data)}\n\n"

            while True:
                try:
                    # Wait for next event or send ping keepalive every 2 seconds
                    event = client_queue.get(timeout=2.0)
                    yield event
                except queue.Empty:
                    yield ": ping\n\n"
        except GeneratorExit:
            with clients_lock:
                if client_queue in sse_clients:
                    sse_clients.remove(client_queue)

    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================
# REST API Endpoints
# =========================================================

@app.route("/api/state", methods=["GET"])
def get_state():
    return jsonify(sim_controller.get_state())


@app.route("/api/node/move", methods=["POST"])
def node_move():
    data = request.get_json() or {}
    name = data.get("name")
    x = float(data.get("x", 0))
    y = float(data.get("y", 0))
    if not name:
        return jsonify({"error": "name required"}), 400
    sim_controller.move_node(name, x, y)
    return jsonify({"success": True})


@app.route("/api/node/toggle", methods=["POST"])
def node_toggle():
    data = request.get_json() or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    new_status = sim_controller.toggle_node(name)
    return jsonify({"name": name, "alive": new_status})


@app.route("/api/kill-random", methods=["POST"])
def kill_random():
    killed = sim_controller.kill_random_node()
    return jsonify({"killed": killed})


@app.route("/api/message/send", methods=["POST"])
def message_send():
    data = request.get_json() or {}
    src = data.get("src")
    dst = data.get("dst")
    payload = data.get("payload", "Data packet")
    msg_type = data.get("type", "chat")
    if not src or not dst:
        return jsonify({"error": "src and dst required"}), 400
    res = sim_controller.send_message(src, dst, payload, msg_type)
    return jsonify(res)


@app.route("/api/alert", methods=["POST"])
def alert():
    data = request.get_json() or {}
    payload = data.get("payload", "EMERGENCY: EVACUATION ALERT")
    res = sim_controller.send_emergency_alert(payload)
    return jsonify(res)


@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.get_json() or {}
    if "n_exponent" in data:
        sim_controller.set_path_loss_exponent(float(data["n_exponent"]))
    if "routing_mode" in data:
        sim_controller.set_routing_mode(data["routing_mode"])
    if "node_count" in data:
        sim_controller.reset_network(int(data["node_count"]))
    return jsonify(sim_controller.get_state()["config"])


@app.route("/api/reset", methods=["POST"])
def reset():
    data = request.get_json() or {}
    count = data.get("node_count")
    sim_controller.reset_network(count=int(count) if count else None)
    return jsonify(sim_controller.get_state())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting MESHage Simulation Server on http://localhost:{port}")
    print(f"Projector Dashboard available at http://localhost:{port}/dashboard")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
