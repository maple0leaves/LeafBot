"""Configuration module for leafbot."""

from leafbot.config.loader import get_config_path, load_config
from leafbot.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
