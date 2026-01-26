"""
Scraper factory for sports data.
Re-exports from training_shift.scraper for backward compatibility.
"""
import sys
from pathlib import Path

# Add src to path
_src_path = Path(__file__).parent.parent.parent / "src"
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from training_shift.scraper import ScraperFactory, MockNBAScraper, MockNFLScraper

__all__ = ["ScraperFactory", "MockNBAScraper", "MockNFLScraper"]

