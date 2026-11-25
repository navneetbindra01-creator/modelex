"""Protocol mapper interface and a generic gateway."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

MAPPERS: dict = {}


def register_mapper(name: str):
    def deco(cls):
        cls.name = name
        MAPPERS[name.upper()] = cls
        return cls
    return deco


def load_mapping(path) -> dict:
    return json.loads(Path(path).read_text()) if path else {}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class ProtocolMapper(ABC):
    """Translates canonical commands/events to and from one wire protocol.

    Mappings (status codes, reject codes, field names) come from a JSON map so
    each venue can match its own published spec without code changes.
    """
    name = "BASE"

    @abstractmethod
    def decode_command(self, raw):
        """Wire message -> canonical command."""

    @abstractmethod
    def encode_command(self, cmd):
        """Canonical command -> wire message (client side; used for testing)."""

    @abstractmethod
    def encode_event(self, ev) -> Optional[object]:
        """Canonical event -> wire message, or None if the protocol does not carry it."""

    @abstractmethod
    def decode_report(self, raw) -> Optional[dict]:
        """Wire message -> normalized dict (see codec.normalize_event)."""


def get_mapper(name: str, config=None) -> ProtocolMapper:
    """Build a mapper, applying any mapping file named in config.protocols[name]."""
    cls = MAPPERS[name.upper()]
    opts = dict((config.protocols.get(name) or {}) if config is not None else {})
    mapping = {}
    if opts.get("mapping_file"):
        mapping = load_mapping(config.resolve_path(opts.pop("mapping_file")))
    return cls(mapping=mapping, **{k: v for k, v in opts.items() if k != "mapping_file"})


class ProtocolGateway:
    """Wire-level front door: raw message in, raw responses out."""

    def __init__(self, exchange, mapper: ProtocolMapper):
        self.exchange = exchange
        self.mapper = mapper

    def handle(self, raw) -> list:
        cmd = self.mapper.decode_command(raw)
        out = []
        for ev in self.exchange.process(cmd):
            msg = self.mapper.encode_event(ev)
            if msg is not None:
                out.append(msg)
        return out
