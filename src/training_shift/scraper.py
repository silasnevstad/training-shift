"""
Scraper factory for sports data.
Assumes existing scrapers that expose this interface.
"""
from typing import Protocol, List, Dict, Any
import random
from datetime import datetime, timedelta


class Scraper(Protocol):
    """Protocol for sports scrapers."""
    
    def scrape_season(self, season: str) -> List[Dict[str, Any]]:
        """Scrape a single season of data."""
        ...


class MockNBAScraper:
    """Mock NBA scraper for demonstration."""
    
    def scrape_season(self, season: str) -> List[Dict[str, Any]]:
        """
        Scrape NBA season data.
        Returns game-level data with team stats.
        
        Args:
            season: Season identifier (e.g., "2021-22")
        
        Returns:
            List of game records
        """
        print(f"Scraping NBA season {season}...")
        
        # Parse season
        start_year = int(season.split("-")[0])
        
        # Generate mock data
        teams = ["LAL", "GSW", "BOS", "MIA", "DEN", "PHX", "MIL", "DAL"]
        games = []
        
        # Simulate ~80 games per team (half as home, half as away)
        num_games = 320  # 8 teams * 40 matchups
        start_date = datetime(start_year, 10, 15)
        
        for i in range(num_games):
            home_team = random.choice(teams)
            away_team = random.choice([t for t in teams if t != home_team])
            
            game_date = start_date + timedelta(days=i // 10)
            
            # Generate realistic stats
            home_pts = random.randint(95, 130)
            away_pts = random.randint(95, 130)
            
            game = {
                "game_id": f"{season}_{i:04d}",
                "season": season,
                "date": game_date.strftime("%Y-%m-%d"),
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_pts,
                "away_score": away_pts,
                "home_fg_pct": round(random.uniform(0.40, 0.52), 3),
                "away_fg_pct": round(random.uniform(0.40, 0.52), 3),
                "home_3p_pct": round(random.uniform(0.30, 0.42), 3),
                "away_3p_pct": round(random.uniform(0.30, 0.42), 3),
                "home_rebounds": random.randint(38, 52),
                "away_rebounds": random.randint(38, 52),
                "home_assists": random.randint(18, 30),
                "away_assists": random.randint(18, 30),
                "home_turnovers": random.randint(10, 18),
                "away_turnovers": random.randint(10, 18),
            }
            
            games.append(game)
        
        print(f"Scraped {len(games)} games for season {season}")
        return games


class MockNFLScraper:
    """Mock NFL scraper for demonstration."""
    
    def scrape_season(self, season: str) -> List[Dict[str, Any]]:
        """
        Scrape NFL season data.
        Returns game-level data with team stats.
        
        Args:
            season: Season identifier (e.g., "2021")
        
        Returns:
            List of game records
        """
        print(f"Scraping NFL season {season}...")
        
        start_year = int(season)
        
        # Generate mock data
        teams = ["KC", "BUF", "SF", "PHI", "DAL", "BAL", "CIN", "LAC"]
        games = []
        
        # NFL has ~17 games per team in regular season
        num_games = 68  # 8 teams * 8.5 matchups
        start_date = datetime(start_year, 9, 5)
        
        for i in range(num_games):
            home_team = random.choice(teams)
            away_team = random.choice([t for t in teams if t != home_team])
            
            game_date = start_date + timedelta(weeks=i // 4)
            
            # Generate realistic stats
            home_pts = random.randint(14, 42)
            away_pts = random.randint(14, 42)
            
            game = {
                "game_id": f"{season}_{i:04d}",
                "season": season,
                "date": game_date.strftime("%Y-%m-%d"),
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_pts,
                "away_score": away_pts,
                "home_total_yards": random.randint(250, 450),
                "away_total_yards": random.randint(250, 450),
                "home_passing_yards": random.randint(180, 350),
                "away_passing_yards": random.randint(180, 350),
                "home_rushing_yards": random.randint(60, 180),
                "away_rushing_yards": random.randint(60, 180),
                "home_turnovers": random.randint(0, 3),
                "away_turnovers": random.randint(0, 3),
            }
            
            games.append(game)
        
        print(f"Scraped {len(games)} games for season {season}")
        return games


class ScraperFactory:
    """Factory for getting sport-specific scrapers."""
    
    _scrapers = {
        "nba": MockNBAScraper,
        "nfl": MockNFLScraper,
    }
    
    @classmethod
    def get_scraper(cls, sport: str) -> Scraper:
        """
        Get a scraper for the specified sport.
        
        Args:
            sport: Sport identifier (e.g., "nba", "nfl")
        
        Returns:
            Scraper instance
        
        Raises:
            ValueError: If sport is not supported
        """
        if sport.lower() not in cls._scrapers:
            raise ValueError(
                f"Sport '{sport}' not supported. "
                f"Available: {list(cls._scrapers.keys())}"
            )
        
        return cls._scrapers[sport.lower()]()
