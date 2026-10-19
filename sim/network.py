"""
network simulation for meshage
"""
import copy
import math
import random
from typing import Dict, List, Optional, Tuple, Union
from core.message import Message
from core.router import FloodingRouter, ShortestPathRouter, GossipRouter
from sim.channel import WirelessChannel


class SimNode:
    def __init__(
        self,
        name: str,
        x: float,
        y: float,
        router_type: str = "flooding",
        gossip_p: float = 0.6,
    ):
        self.name = name
        self.x = x
        self.y = y
        self.is_alive = True
        self.alive = True
        self.neighbors: List[str] = []

        if router_type == "shortest":
            self.router = ShortestPathRouter(node_name=name, neighbors=lambda: self.neighbors)
        elif router_type == "gossip":
            self.router = GossipRouter(node_name=name, neighbors=lambda: self.neighbors, p=gossip_p)
        else:
            self.router = FloodingRouter(node_name=name, neighbors=lambda: self.neighbors)


class Network:
    def __init__(
        self,
        transmission_range: float = 40.0,
        channel: Optional[WirelessChannel] = None,
        seed: Optional[int] = 42,
        default_router: str = "flooding",
    ):
        self.transmission_range = transmission_range
        self.channel = channel if channel is not None else WirelessChannel()
        self.seed = seed
        self.rng = random.Random(seed)
        self.default_router = default_router
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

    def add_node(
        self,
        name: str,
        x: float,
        y: float,
        router_type: Optional[str] = None,
        gossip_p: float = 0.6,
    ) -> SimNode:
        rtype = router_type if router_type is not None else self.default_router
        node = SimNode(name, x, y, router_type=rtype, gossip_p=gossip_p)
        self.nodes[name] = node
        return node

    def kill_node(self, name: str) -> None:
        if name in self.nodes:
            self.nodes[name].is_alive = False
            self.nodes[name].alive = False

    def revive_node(self, name: str) -> None:
        if name in self.nodes:
            self.nodes[name].is_alive = True
            self.nodes[name].alive = True

    def distance(self, name1: str, name2: str) -> float:
        n1 = self.nodes[name1]
        n2 = self.nodes[name2]
        return math.hypot(n1.x - n2.x, n1.y - n2.y)

    def build_links(self) -> None:
        # connect nodes within transmission range and update link costs
        for node in self.nodes.values():
            node.neighbors = []

        names = list(self.nodes.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                dist = self.distance(names[i], names[j])
                if dist <= self.transmission_range:
                    n1 = self.nodes[names[i]]
                    n2 = self.nodes[names[j]]
                    n1.neighbors.append(names[j])
                    n2.neighbors.append(names[i])

                    # update link cost based on packet success probability
                    p = self.channel.packet_success_from_distance(dist, shadowing=False)
                    cost = 1.0 / max(p, 0.05)
                    if hasattr(n1.router, "set_link_cost"):
                        n1.router.set_link_cost(names[j], cost)
                    if hasattr(n2.router, "set_link_cost"):
                        n2.router.set_link_cost(names[i], cost)

    def broadcast_hellos(self) -> None:
        # periodic hello exchange for link-state and failure detection
        for node in self.nodes.values():
            if not node.is_alive:
                continue

            if hasattr(node.router, "tick"):
                node.router.tick()

            if hasattr(node.router, "create_hello"):
                hello_msg = node.router.create_hello()
                for nbr in node.neighbors:
                    self.in_flight.append((nbr, copy.deepcopy(hello_msg), node.name))

    def send_message(
        self,
        src: str,
        dst: str,
        payload: str,
        msg_type: str = "chat",
        ttl: int = 10,
    ) -> Optional[Message]:
        src_node = self.nodes.get(src)
        if not src_node or not src_node.is_alive:
            return None

        msg = Message(
            src=src,
            dst=dst,
            payload=payload,
            type=msg_type,
            ttl=ttl,
        )
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
            # check target node exists and is alive
            if target_name not in self.nodes:
                continue
            target_node = self.nodes[target_name]
            if not target_node.is_alive:
                continue

            # check sender node status
            if from_node and from_node in self.nodes:
                sender_node = self.nodes[from_node]
                if not sender_node.is_alive:
                    continue

                dist = self.distance(from_node, target_name)
                self.total_transmissions += 1
                succeeded = self.channel.transmits_successfully(dist, rng=self.rng)
                if not succeeded:
                    self.dropped_transmissions += 1
                    continue
                self.successful_transmissions += 1

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
