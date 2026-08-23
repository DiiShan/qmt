"""QMT local research database."""

from .config import DataConfig, load_config
from .research import ResearchData

__all__ = ["DataConfig", "ResearchData", "load_config"]
__version__ = "0.1.0"
