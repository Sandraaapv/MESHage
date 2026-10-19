"""
routing algorithms for meshage: flooding, shortest path (dijkstra), and gossip
"""
import heapq
import json
import random
from typing import Callable, Dict, List, Optional, Union
from core.message import Message


def dijkstra_next_hop(
    graph: Dict[str, Dict[str, float]],
    src: str,
    dst: str,
) -> Optional[str]:
    # find first hop on shortest weighted path from src to dst
    if src not in graph or dst not in graph or src == dst:
        return None

    distances = {src: 0.0}
    previous = {}
    pq = [(0.0, src)]
    visited = set()

    while pq:
        curr_dist, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)

        if u == dst:
            break

        for v, cost in graph.get(u, {}).items():
            new_dist = curr_dist + cost
            if new_dist < distances.get(v, float("inf")):
                distances[v] = new_dist
                previous[v] = u
                heapq.heappush(pq, (new_dist, v))

    if dst not in previous:
        return None

    # backtrack to find immediate next hop from src
    curr = dst
    path = [curr]
    while curr in previous:
        curr = previous[curr]
        path.append(curr)
    path.reverse()

    return path[1] if len(path) > 1 else None


class FloodingRouter:
    def __init__(
        self,
        node_name: str,
        neighbors: Optional[Union[List[str], Callable[[], List[str]]]] = None,
        on_deliver: Optional[Callable[[Message], None]] = None,
    ):
        self.node_name = node_name
        self.neighbors = neighbors if neighbors is not None else []
        self.seen_ids = set()
        self.delivered_messages: List[Message] = []
        self.on_deliver = on_deliver

    def get_neighbors(self) -> List[str]:
        if callable(self.neighbors):
            return list(self.neighbors())
        return list(self.neighbors)

    def handle(self, message: Message, from_node: Optional[str] = None) -> List[str]:
        if message.id in self.seen_ids:
            return []
        self.seen_ids.add(message.id)

        if message.ttl <= 0:
            return []

        message.path.append(self.node_name)
        message.ttl -= 1

        if message.dst == self.node_name or message.dst == "ALL":
            self.delivered_messages.append(message)
            if self.on_deliver:
                self.on_deliver(message)
            if message.dst != "ALL":
                return []

        if message.ttl <= 0:
            return []

        neighbors = self.get_neighbors()
        return [nbr for nbr in neighbors if nbr != from_node and nbr != self.node_name]


class ShortestPathRouter:
    def __init__(
        self,
        node_name: str,
        neighbors: Optional[Union[List[str], Callable[[], List[str]]]] = None,
        on_deliver: Optional[Callable[[Message], None]] = None,
        missed_threshold: int = 3,
    ):
        self.node_name = node_name
        self.neighbors = neighbors if neighbors is not None else []
        self.on_deliver = on_deliver
        self.missed_threshold = missed_threshold
        self.seen_ids = set()
        self.delivered_messages: List[Message] = []

        # neighbor_table: {neighbor_name: {"status": "UP", "missed_hellos": int, "cost": float}}
        self.neighbor_table: Dict[str, dict] = {}
        # link_state_map: {node_u: {node_v: cost}}
        self.link_state_map: Dict[str, Dict[str, float]] = {}

    def get_direct_neighbors(self) -> List[str]:
        if callable(self.neighbors):
            return list(self.neighbors())
        return list(self.neighbors)

    def get_active_neighbors(self) -> List[str]:
        # return active direct neighbors marked as UP
        active = []
        for nbr in self.get_direct_neighbors():
            info = self.neighbor_table.get(nbr)
            if info is None or info.get("status", "UP") == "UP":
                active.append(nbr)
        return active

    def set_link_cost(self, neighbor: str, cost: float) -> None:
        if neighbor not in self.neighbor_table:
            self.neighbor_table[neighbor] = {"status": "UP", "missed_hellos": 0, "cost": cost}
        else:
            self.neighbor_table[neighbor]["cost"] = cost

        if self.node_name not in self.link_state_map:
            self.link_state_map[self.node_name] = {}
        self.link_state_map[self.node_name][neighbor] = cost

    def create_hello(self) -> Message:
        # build hello packet with list of active neighbors and known links
        active = self.get_active_neighbors()
        # include direct link costs
        links_payload = {}
        for u, nbrs in self.link_state_map.items():
            links_payload[u] = dict(nbrs)

        payload_dict = {
            "node": self.node_name,
            "neighbors": active,
            "links": links_payload,
        }
        return Message(
            src=self.node_name,
            dst="ALL",
            payload=json.dumps(payload_dict),
            type="hello",
            ttl=1,
        )

    def tick(self) -> List[str]:
        # called on every hello interval: track missed hellos and mark down failed nodes
        downed = []
        for nbr in self.get_direct_neighbors():
            if nbr not in self.neighbor_table:
                self.neighbor_table[nbr] = {"status": "UP", "missed_hellos": 0, "cost": 1.0}

            info = self.neighbor_table[nbr]
            info["missed_hellos"] += 1

            if info["missed_hellos"] >= self.missed_threshold and info["status"] == "UP":
                info["status"] = "DOWN"
                downed.append(nbr)
                # remove links involving this neighbor
                if self.node_name in self.link_state_map and nbr in self.link_state_map[self.node_name]:
                    del self.link_state_map[self.node_name][nbr]
                if nbr in self.link_state_map:
                    del self.link_state_map[nbr]

        return downed

    def process_hello(self, message: Message, from_node: Optional[str] = None) -> None:
        sender = message.src
        if not sender:
            return

        # mark sender as alive and reset missed count
        if sender not in self.neighbor_table:
            self.neighbor_table[sender] = {"status": "UP", "missed_hellos": 0, "cost": 1.0}
        else:
            self.neighbor_table[sender]["status"] = "UP"
            self.neighbor_table[sender]["missed_hellos"] = 0

        # parse payload
        try:
            data = json.loads(message.payload)
            sender_neighbors = data.get("neighbors", [])
            shared_links = data.get("links", {})

            # ensure direct link between self and sender
            cost = self.neighbor_table[sender].get("cost", 1.0)
            if self.node_name not in self.link_state_map:
                self.link_state_map[self.node_name] = {}
            self.link_state_map[self.node_name][sender] = cost

            if sender not in self.link_state_map:
                self.link_state_map[sender] = {}
            self.link_state_map[sender][self.node_name] = cost

            # merge shared link-state topology
            for u, nbrs in shared_links.items():
                if u not in self.link_state_map:
                    self.link_state_map[u] = {}
                for v, c in nbrs.items():
                    self.link_state_map[u][v] = c

            # update sender's neighbors
            for nbr in sender_neighbors:
                if nbr not in self.link_state_map[sender]:
                    self.link_state_map[sender][nbr] = 1.0

        except Exception:
            pass

    def compute_route(self, dst: str) -> Optional[str]:
        # build clean graph of active nodes
        graph: Dict[str, Dict[str, float]] = {}
        active_direct = set(self.get_active_neighbors())

        for u, nbrs in self.link_state_map.items():
            # if u is a direct neighbor and DOWN, omit
            if u in self.neighbor_table and self.neighbor_table[u]["status"] == "DOWN":
                continue
            graph[u] = {}
            for v, cost in nbrs.items():
                if v in self.neighbor_table and self.neighbor_table[v]["status"] == "DOWN":
                    continue
                graph[u][v] = cost

        next_hop = dijkstra_next_hop(graph, self.node_name, dst)
        if next_hop and next_hop in active_direct:
            return next_hop
        return None

    def handle(self, message: Message, from_node: Optional[str] = None) -> List[str]:
        # ignore messages seen before
        if message.id in self.seen_ids:
            return []
        self.seen_ids.add(message.id)

        if message.ttl <= 0:
            return []

        message.path.append(self.node_name)
        message.ttl -= 1

        # handle hello message
        if message.type == "hello":
            self.process_hello(message, from_node)
            return []

        # deliver locally if destination or broadcast
        if message.dst == self.node_name or message.dst == "ALL":
            self.delivered_messages.append(message)
            if self.on_deliver:
                self.on_deliver(message)
            if message.dst != "ALL":
                return []

        if message.ttl <= 0:
            return []

        # broadcast message
        if message.dst == "ALL":
            active_nbrs = self.get_active_neighbors()
            return [nbr for nbr in active_nbrs if nbr != from_node and nbr != self.node_name]

        # unicast message: compute next hop using dijkstra
        next_hop = self.compute_route(message.dst)
        if next_hop and next_hop != from_node and next_hop in self.get_active_neighbors():
            return [next_hop]

        return []


class GossipRouter:
    def __init__(
        self,
        node_name: str,
        neighbors: Optional[Union[List[str], Callable[[], List[str]]]] = None,
        p: float = 0.6,
        on_deliver: Optional[Callable[[Message], None]] = None,
        rng: Optional[random.Random] = None,
    ):
        self.node_name = node_name
        self.neighbors = neighbors if neighbors is not None else []
        self.p = p
        self.on_deliver = on_deliver
        self.rng = rng if rng is not None else random.Random()
        self.seen_ids = set()
        self.delivered_messages: List[Message] = []

    def get_neighbors(self) -> List[str]:
        if callable(self.neighbors):
            return list(self.neighbors())
        return list(self.neighbors)

    def handle(self, message: Message, from_node: Optional[str] = None) -> List[str]:
        if message.id in self.seen_ids:
            return []
        self.seen_ids.add(message.id)

        if message.ttl <= 0:
            return []

        message.path.append(self.node_name)
        message.ttl -= 1

        if message.dst == self.node_name or message.dst == "ALL":
            self.delivered_messages.append(message)
            if self.on_deliver:
                self.on_deliver(message)
            if message.dst != "ALL":
                return []

        if message.ttl <= 0:
            return []

        candidates = [
            nbr for nbr in self.get_neighbors()
            if nbr != from_node and nbr != self.node_name
        ]
        # forward to each neighbor with probability p
        return [nbr for nbr in candidates if self.rng.random() < self.p]
