"""
mesh node for android termux and laptop
runs udp listener, routing, hello broadcasts, and event logging
"""
import argparse
import copy
import json
import os
import queue
import socket
import sys
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

# ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.message import Message
from core.router import FloodingRouter, ShortestPathRouter, GossipRouter


def parse_neighbor_arg(arg: str) -> List[Tuple[str, int]]:
    # parse comma-separated host:port list
    neighbors = []
    if not arg:
        return neighbors
    for item in arg.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.rsplit(":", 1)
        if len(parts) == 2:
            host = parts[0].strip()
            port = int(parts[1].strip())
            neighbors.append((host, port))
    return neighbors


class MeshNode:
    def __init__(
        self,
        name: str,
        port: int = 5001,
        host: str = "0.0.0.0",
        neighbors: Optional[List[Tuple[str, int]]] = None,
        routing: str = "flooding",
        hello_interval: float = 3.0,
        missed_threshold: int = 3,
        gossip_p: float = 0.6,
        api_port: Optional[int] = None,
    ):
        self.name = name
        self.port = port
        self.host = host
        self.routing_mode = routing.lower()
        self.hello_interval = hello_interval
        self.missed_threshold = missed_threshold
        self.gossip_p = gossip_p
        self.api_port = api_port

        # configured neighbor socket addresses
        self.neighbor_addrs: List[Tuple[str, int]] = neighbors if neighbors else []

        # name to addr mapping learned from hellos: {"B": ("127.0.0.1", 5002)}
        self.name_to_addr: Dict[str, Tuple[str, int]] = {}
        self.addr_to_name: Dict[Tuple[str, int], str] = {}

        # neighbor status: {"B": {"status": "UP", "last_seen": timestamp, "addr": (...)}}
        self.neighbor_table: Dict[str, dict] = {}

        # in-memory event and message logs
        self.events: List[dict] = []
        self.messages: List[dict] = []
        self.counters = {"sent": 0, "received": 0, "relayed": 0, "delivered": 0, "dropped": 0}
        self.event_subscribers: List[queue.Queue] = []
        self.running = False
        self.sock: Optional[socket.socket] = None
        self.api_thread: Optional[threading.Thread] = None

        # router setup
        self._init_router()

        # thread locks
        self.lock = threading.Lock()

    def _init_router(self) -> None:
        if self.routing_mode == "shortest":
            self.router = ShortestPathRouter(
                node_name=self.name,
                neighbors=self.get_active_neighbor_names,
                missed_threshold=self.missed_threshold,
            )
        elif self.routing_mode == "gossip":
            self.router = GossipRouter(
                node_name=self.name,
                neighbors=self.get_active_neighbor_names,
                p=self.gossip_p,
            )
        else:
            self.router = FloodingRouter(
                node_name=self.name,
                neighbors=self.get_active_neighbor_names,
            )

    def log_event(self, event_type: str, description: str, data: Optional[dict] = None) -> None:
        ts = time.time()
        time_str = time.strftime("%H:%M:%S", time.localtime(ts))
        event = {
            "timestamp": ts,
            "type": event_type,
            "description": description,
            "data": data or {},
        }
        with self.lock:
            if event_type in self.counters:
                self.counters[event_type] += 1
            self.events.append(event)
            for q in list(self.event_subscribers):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass
        # print to console
        print(f"[{time_str}] [{event_type.upper()}] {description}", flush=True)

    def is_allowed_sender(self, addr: Tuple[str, int]) -> bool:
        # only talk to the listed neighbors
        s_host, s_port = addr
        for n_host, n_port in self.neighbor_addrs:
            if s_port == n_port:
                if s_host == n_host:
                    return True
                # allow localhost aliases (127.0.0.1 vs localhost)
                if s_host in ("127.0.0.1", "localhost") and n_host in ("127.0.0.1", "localhost"):
                    return True
        return False

    def get_active_neighbor_names(self) -> List[str]:
        # return list of known neighbor names that are UP
        active = []
        for name, info in self.neighbor_table.items():
            if info.get("status") == "UP":
                active.append(name)
        return active

    def start(self) -> None:
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # allow address reuse
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))

        print(f"Node '{self.name}' started on {self.host}:{self.port} (routing: {self.routing_mode})")
        print(f"Configured neighbors: {self.neighbor_addrs}")

        # start background listener thread
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()

        # start background hello and timeout thread
        self.hello_thread = threading.Thread(target=self._hello_loop, daemon=True)
        self.hello_thread.start()

        # start background flask api server if api_port configured
        if self.api_port:
            from node.api import start_api_server
            self.api_thread = start_api_server(self, host=self.host, port=self.api_port)
            print(f"API server running on http://{self.host}:{self.api_port}")

    def stop(self) -> None:
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def _listen_loop(self) -> None:
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
                self._handle_incoming_packet(data, addr)
            except (socket.error, OSError):
                if not self.running:
                    break

    def _handle_incoming_packet(self, data: bytes, sender_addr: Tuple[str, int]) -> None:
        # check neighbor whitelist
        if not self.is_allowed_sender(sender_addr):
            self.log_event(
                "dropped",
                f"Ignored packet from unlisted sender {sender_addr[0]}:{sender_addr[1]}",
                {"sender": sender_addr},
            )
            return

        try:
            msg = Message.from_json(data.decode("utf-8"))
        except Exception as e:
            self.log_event("dropped", f"Malformed packet from {sender_addr}: {e}")
            return

        sender_name = msg.src

        # learn and update neighbor mapping
        if sender_name:
            prev_status = self.neighbor_table.get(sender_name, {}).get("status")
            with self.lock:
                self.name_to_addr[sender_name] = sender_addr
                self.addr_to_name[sender_addr] = sender_name
                self.neighbor_table[sender_name] = {
                    "status": "UP",
                    "last_seen": time.time(),
                    "addr": sender_addr,
                }
            if prev_status != "UP":
                self.log_event(
                    "neighbor_up",
                    f"Neighbor '{sender_name}' is UP at {sender_addr[0]}:{sender_addr[1]}",
                    {"name": sender_name, "addr": sender_addr},
                )

        # log received packet
        if msg.type != "hello":
            self.log_event(
                "received",
                f"Received {msg.type} message from '{msg.src}' via {sender_addr[0]}:{sender_addr[1]}",
                {"id": msg.id, "src": msg.src, "dst": msg.dst},
            )

        # handle message through core router
        from_node = msg.path[-1] if msg.path else sender_name
        next_hops = self.router.handle(msg, from_node=from_node)

        # check if delivered locally
        if msg.dst == self.name or msg.dst == "ALL":
            if msg.type != "hello":
                path_str = " -> ".join(msg.path)
                self.log_event(
                    "delivered",
                    f"Message from '{msg.src}': '{msg.payload}' (path: {path_str})",
                    {"id": msg.id, "src": msg.src, "payload": msg.payload, "path": msg.path},
                )
                with self.lock:
                    self.messages.append({
                        "id": msg.id,
                        "src": msg.src,
                        "dst": msg.dst,
                        "payload": msg.payload,
                        "path": msg.path,
                        "timestamp": msg.timestamp,
                        "type": msg.type,
                    })

        # forward message to next hops
        for nxt in next_hops:
            self._forward_to_neighbor(nxt, msg)

    def _forward_to_neighbor(self, nxt_name: str, msg: Message) -> None:
        target_addr = self.name_to_addr.get(nxt_name)
        if not target_addr:
            return

        try:
            payload_bytes = msg.to_json().encode("utf-8")
            self.sock.sendto(payload_bytes, target_addr)
            if msg.type != "hello":
                self.log_event(
                    "relayed",
                    f"Forwarded message {msg.id[:8]} to '{nxt_name}' at {target_addr[0]}:{target_addr[1]}",
                    {"id": msg.id, "next_hop": nxt_name, "path": msg.path},
                )
        except Exception as e:
            self.log_event("dropped", f"Failed forwarding to {nxt_name}: {e}")

    def send_chat(self, dst: str, payload: str, msg_type: str = "chat", ttl: int = 10) -> Optional[Message]:
        # originate a new message from this node
        msg = Message(
            src=self.name,
            dst=dst,
            payload=payload,
            type=msg_type,
            ttl=ttl,
        )

        self.log_event(
            "sent",
            f"Sending {msg_type} to '{dst}': '{payload}'",
            {"id": msg.id, "dst": dst, "payload": payload},
        )

        with self.lock:
            self.messages.append({
                "id": msg.id,
                "src": self.name,
                "dst": dst,
                "payload": payload,
                "path": [self.name],
                "timestamp": msg.timestamp,
                "type": msg_type,
            })

        next_hops = self.router.handle(msg, from_node=None)

        if not next_hops:
            # fallback if neighbor names not yet mapped: send to all configured addresses
            if msg.dst == "ALL" or self.routing_mode == "flooding":
                for addr in self.neighbor_addrs:
                    try:
                        self.sock.sendto(msg.to_json().encode("utf-8"), addr)
                    except Exception:
                        pass
            return msg

        for nxt in next_hops:
            self._forward_to_neighbor(nxt, msg)
        return msg

    def _hello_loop(self) -> None:
        # periodic hello exchange and neighbor timeout tracking
        while self.running:
            time.sleep(self.hello_interval)
            now = time.time()
            timeout_limit = self.hello_interval * self.missed_threshold

            # 1. check neighbor timeouts
            with self.lock:
                for name, info in list(self.neighbor_table.items()):
                    if info["status"] == "UP" and (now - info["last_seen"]) > timeout_limit:
                        info["status"] = "DOWN"
                        self.log_event(
                            "neighbor_down",
                            f"Neighbor '{name}' timed out and marked DOWN",
                            {"name": name},
                        )
                        if hasattr(self.router, "neighbor_table") and name in self.router.neighbor_table:
                            self.router.neighbor_table[name]["status"] = "DOWN"

            if hasattr(self.router, "tick"):
                self.router.tick()

            # 2. send hello packet to all configured neighbors
            if hasattr(self.router, "create_hello"):
                hello = self.router.create_hello()
            else:
                hello = Message(
                    src=self.name,
                    dst="ALL",
                    payload=json.dumps({"node": self.name, "neighbors": self.get_active_neighbor_names()}),
                    type="hello",
                    ttl=1,
                )

            hello_bytes = hello.to_json().encode("utf-8")
            for addr in self.neighbor_addrs:
                try:
                    self.sock.sendto(hello_bytes, addr)
                except Exception:
                    pass


def run_cli(node: MeshNode) -> None:
    # interactive command loop in terminal
    print("\nCommands:")
    print("  send <dst> <message>    - send chat message")
    print("  alert <message>         - broadcast emergency alert to ALL")
    print("  status                  - show node status and neighbors")
    print("  exit                    - stop node and quit\n")

    while node.running:
        try:
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.5)
                continue
            line = line.strip()
            if not line:
                continue

            parts = line.split(maxsplit=2)
            cmd = parts[0].lower()

            if cmd in ("exit", "quit"):
                break
            elif cmd == "status":
                active = node.get_active_neighbor_names()
                print(f"Node: {node.name} (port {node.port}, mode: {node.routing_mode})")
                print(f"Active neighbors: {active}")
                print(f"Total events: {len(node.events)}, messages: {len(node.messages)}")
            elif cmd == "send" and len(parts) >= 3:
                dst = parts[1]
                msg_text = parts[2]
                node.send_chat(dst, msg_text)
            elif cmd == "alert" and len(parts) >= 2:
                alert_text = line[len(cmd):].strip()
                node.send_chat("ALL", alert_text, msg_type="emergency")
            elif len(parts) >= 2:
                # convenience syntax: <dst> <message>
                dst = parts[0]
                msg_text = line[len(dst):].strip()
                node.send_chat(dst, msg_text)
            else:
                print("Unknown command. Use: send <dst> <message> or alert <message>")
        except (KeyboardInterrupt, EOFError):
            break

    print(f"Stopping node '{node.name}'...")
    node.stop()


def main():
    parser = argparse.ArgumentParser(description="MESHage UDP Mesh Node")
    parser.add_argument("--name", required=True, help="Node name (e.g. A)")
    parser.add_argument("--port", type=int, default=5001, help="UDP listening port")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host IP")
    parser.add_argument(
        "--neighbors",
        default="",
        help="Comma-separated list of neighbor ip:port (e.g. 192.168.43.5:5001,192.168.43.7:5001)",
    )
    parser.add_argument(
        "--routing",
        default="flooding",
        choices=["flooding", "shortest", "gossip"],
        help="Routing algorithm",
    )
    parser.add_argument("--hello-interval", type=float, default=2.5, help="Hello broadcast interval in seconds")
    parser.add_argument("--api-port", type=int, default=None, help="Flask API HTTP port")
    parser.add_argument("--non-interactive", action="store_true", help="Run without stdin CLI loop")

    args = parser.parse_args()

    neighbors = parse_neighbor_arg(args.neighbors)
    node = MeshNode(
        name=args.name,
        port=args.port,
        host=args.host,
        neighbors=neighbors,
        routing=args.routing,
        hello_interval=args.hello_interval,
        api_port=args.api_port,
    )

    node.start()

    if args.non_interactive:
        try:
            while node.running:
                time.sleep(1)
        except KeyboardInterrupt:
            node.stop()
    else:
        run_cli(node)


if __name__ == "__main__":
    main()
