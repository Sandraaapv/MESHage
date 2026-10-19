"""
network simulation for meshage
"""
import copy
import math
from typing import Dict, List, Optional, Tuple
from core.message import Message
from core.router import FloodingRouter


class SimNode:
    def __init__(self, name: str, x: float, y: float):
        self.name = name
        self.x = x
        self.y = y
        self.neighbors: List[str] = []
        self.router = FloodingRouter(node_name=name, neighbors=lambda: self.neighbors)


class Network:
    def __init__(self, transmission_range: float = 35.0):
        self.transmission_range = transmission_range
        self.nodes: Dict[str, SimNode] = {}
        # (target_node, message, from_node)
        self.in_flight: List[Tuple[str, Message, Optional[str]]] = []
        self.time_step: int = 0

    def add_node(self, name: str, x: float, y: float) -> SimNode:
        node = SimNode(name, x, y)
        self.nodes[name] = node
        return node

    def build_links(self) -> None:
        # connect nodes within transmission range
        for node in self.nodes.values():
            node.neighbors = []

        names = list(self.nodes.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                n1 = self.nodes[names[i]]
                n2 = self.nodes[names[j]]
                dist = math.hypot(n1.x - n2.x, n1.y - n2.y)
                if dist <= self.transmission_range:
                    n1.neighbors.append(n2.name)
                    n2.neighbors.append(n1.name)

    def send_message(
        self,
        src: str,
        dst: str,
        payload: str,
        msg_type: str = "chat",
        ttl: int = 10,
    ) -> Message:
        msg = Message(
            src=src,
            dst=dst,
            payload=payload,
            type=msg_type,
            ttl=ttl,
        )
        src_node = self.nodes[src]
        next_hops = src_node.router.handle(msg, from_node=None)
        for nxt in next_hops:
            self.in_flight.append((nxt, copy.deepcopy(msg), src))
        return msg

    def step(self) -> int:
        # move messages forward by one hop
        if not self.in_flight:
            return 0

        current_batch = self.in_flight
        self.in_flight = []

        for target_name, msg, from_node in current_batch:
            if target_name not in self.nodes:
                continue
            target_node = self.nodes[target_name]
            next_hops = target_node.router.handle(msg, from_node=from_node)
            for nxt in next_hops:
                self.in_flight.append((nxt, copy.deepcopy(msg), target_name))

        self.time_step += 1
        return len(current_batch)

    def has_active_messages(self) -> bool:
        return len(self.in_flight) > 0

    def run(self, max_steps: int = 100) -> int:
        steps = 0
        while self.has_active_messages() and steps < max_steps:
            self.step()
            steps += 1
        return steps
