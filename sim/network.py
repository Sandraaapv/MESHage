"""
network simulation for meshage
"""
import copy
import math
import random
from typing import Dict, List, Optional, Tuple
from core.message import Message
from core.router import FloodingRouter
from sim.channel import WirelessChannel


class SimNode:
    def __init__(self, name: str, x: float, y: float):
        self.name = name
        self.x = x
        self.y = y
        self.neighbors: List[str] = []
        self.router = FloodingRouter(node_name=name, neighbors=lambda: self.neighbors)


class Network:
    def __init__(
        self,
        transmission_range: float = 40.0,
        channel: Optional[WirelessChannel] = None,
        seed: Optional[int] = 42,
    ):
        self.transmission_range = transmission_range
        self.channel = channel if channel is not None else WirelessChannel()
        self.seed = seed
        self.rng = random.Random(seed)
        self.nodes: Dict[str, SimNode] = {}
        # (target_node, message, from_node)
        self.in_flight: List[Tuple[str, Message, Optional[str]]] = []
        self.time_step: int = 0
        self.total_transmissions: int = 0
        self.dropped_transmissions: int = 0
        self.successful_transmissions: int = 0

    def set_seed(self, seed: Optional[int]) -> None:
        self.seed = seed
        self.rng = random.Random(seed)

    def add_node(self, name: str, x: float, y: float) -> SimNode:
        node = SimNode(name, x, y)
        self.nodes[name] = node
        return node

    def distance(self, name1: str, name2: str) -> float:
        n1 = self.nodes[name1]
        n2 = self.nodes[name2]
        return math.hypot(n1.x - n2.x, n1.y - n2.y)

    def build_links(self) -> None:
        # connect nodes within candidate transmission range
        for node in self.nodes.values():
            node.neighbors = []

        names = list(self.nodes.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                dist = self.distance(names[i], names[j])
                if dist <= self.transmission_range:
                    self.nodes[names[i]].neighbors.append(names[j])
                    self.nodes[names[j]].neighbors.append(names[i])

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
        # move messages forward by one hop with wireless channel model
        if not self.in_flight:
            return 0

        current_batch = self.in_flight
        self.in_flight = []

        for target_name, msg, from_node in current_batch:
            if target_name not in self.nodes:
                continue

            # check packet loss over wireless channel
            if from_node and from_node in self.nodes:
                dist = self.distance(from_node, target_name)
                self.total_transmissions += 1
                succeeded = self.channel.transmits_successfully(dist, rng=self.rng)
                if not succeeded:
                    self.dropped_transmissions += 1
                    continue
                self.successful_transmissions += 1

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
