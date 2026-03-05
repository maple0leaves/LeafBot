"""Message bus module for decoupled channel-agent communication."""

from leafbot.bus.events import InboundMessage, OutboundMessage
from leafbot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
