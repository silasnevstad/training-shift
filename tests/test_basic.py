"""
Basic integration test for the training-shift pipeline.
"""
import sys
from pathlib import Path

# Add repository root to path
_repo_root = Path(__file__).parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Add src directory to path
_src_dir = _repo_root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from training_shift.scraper import ScraperFactory
from training_shift.dataset import DatasetBuilder
from training_shift.trainer import BaselineTrainer


def test_scraper_factory():
    """Test scraper factory."""
    # Test NBA scraper
    nba_scraper = ScraperFactory.get_scraper("nba")
    assert nba_scraper is not None
    
    # Test NFL scraper
    nfl_scraper = ScraperFactory.get_scraper("nfl")
    assert nfl_scraper is not None
    
    print("✓ Scraper factory test passed")


def test_nba_scraper():
    """Test NBA scraper."""
    scraper = ScraperFactory.get_scraper("nba")
    games = scraper.scrape_season("2021-22")
    
    assert len(games) > 0
    assert "game_id" in games[0]
    assert "home_team" in games[0]
    assert "away_team" in games[0]
    
    print(f"✓ NBA scraper test passed ({len(games)} games)")


def test_nfl_scraper():
    """Test NFL scraper."""
    scraper = ScraperFactory.get_scraper("nfl")
    games = scraper.scrape_season("2021")
    
    assert len(games) > 0
    assert "game_id" in games[0]
    assert "home_team" in games[0]
    assert "away_team" in games[0]
    
    print(f"✓ NFL scraper test passed ({len(games)} games)")


if __name__ == "__main__":
    test_scraper_factory()
    test_nba_scraper()
    test_nfl_scraper()
    print("\n✓ All tests passed!")
