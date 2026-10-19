"""
message format for meshage
"""
from dataclasses import dataclass, field, asdict, fields
import json
import time
import uuid
from typing import List


@dataclass
class Message:
    src: str = ""
    dst: str = ""
    payload: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ttl: int = 10
    path: List[str] = field(default_factory=list)
    type: str = "chat"
    timestamp: float = field(default_factory=time.time)
    nonce: str = ""

    def to_json(self) -> str:
        # serialize message to json string
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "Message":
        # deserialize message from json string safely ignoring unknown fields
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        parsed = json.loads(data)
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in parsed.items() if k in valid_fields}
        return cls(**filtered)
