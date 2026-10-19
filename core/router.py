"""
flooding router for meshage
"""
from typing import Callable, List, Optional, Union
from core.message import Message


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
        # get list of current neighbors
        if callable(self.neighbors):
            return list(self.neighbors())
        return list(self.neighbors)

    def handle(self, message: Message, from_node: Optional[str] = None) -> List[str]:
        # ignore message if seen before
        if message.id in self.seen_ids:
            return []
        self.seen_ids.add(message.id)

        # drop message if ttl is 0
        if message.ttl <= 0:
            return []

        # append this node to the hop path
        message.path.append(self.node_name)

        # decrement ttl
        message.ttl -= 1

        # deliver locally if this node is destination or message is for all
        if message.dst == self.node_name or message.dst == "ALL":
            self.delivered_messages.append(message)
            if self.on_deliver:
                self.on_deliver(message)
            if message.dst != "ALL":
                # unicast arrived at destination, stop forwarding
                return []

        # stop forwarding if ttl expired
        if message.ttl <= 0:
            return []

        # forward to all neighbors except sender
        neighbors = self.get_neighbors()
        return [nbr for nbr in neighbors if nbr != from_node and nbr != self.node_name]
