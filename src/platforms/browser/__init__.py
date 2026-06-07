"""
Browser platform for poker games.
Supports multiple websites via adapters.
"""
from .browser_platform import BrowserPlatform, BrowserPlatformConfig, TableSelectionStrategy
from .auto_player import BrowserAutoPlayer
from .exit_checker import ExitChecker
from .human_delay import human_delay