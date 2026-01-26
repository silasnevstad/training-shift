"""
Dataset builder for team-level supervised learning with time-based splits.
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


class DatasetBuilder:
    """Build supervised datasets from scraped game data."""
    
    def __init__(self, data_dir: Path):
        """
        Initialize dataset builder.
        
        Args:
            data_dir: Directory containing raw scraped data
        """
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
    
    def build_team_level_dataset(
        self,
        sport: str,
        target: str = "win",
        feature_drop: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Build team-level dataset from game data.
        
        Args:
            sport: Sport identifier (e.g., "nba", "nfl")
            target: Target variable ("win" or "score_diff")
            feature_drop: Optional list of features to drop (for schema drift)
        
        Returns:
            DataFrame with team-level features and target
        """
        print(f"Building {sport} team-level dataset...")
        
        # Load all scraped games
        games = []
        sport_dir = self.raw_dir / sport
        
        if not sport_dir.exists():
            raise ValueError(f"No data found for sport '{sport}' in {sport_dir}")
        
        for season_file in sorted(sport_dir.glob("*.json")):
            with open(season_file, "r") as f:
                season_games = json.load(f)
                games.extend(season_games)
        
        if not games:
            raise ValueError(f"No games found for sport '{sport}'")
        
        print(f"Loaded {len(games)} games")
        
        # Convert to team-level observations (each game = 2 rows)
        rows = []
        
        for game in games:
            # Home team observation
            home_row = self._create_team_observation(
                game, is_home=True, sport=sport, target=target
            )
            rows.append(home_row)
            
            # Away team observation
            away_row = self._create_team_observation(
                game, is_home=False, sport=sport, target=target
            )
            rows.append(away_row)
        
        df = pd.DataFrame(rows)
        
        # Apply feature drop if specified (schema drift simulation)
        if feature_drop:
            print(f"Applying feature drop: {feature_drop}")
            existing_drops = [f for f in feature_drop if f in df.columns]
            if existing_drops:
                df = df.drop(columns=existing_drops)
                print(f"Dropped features: {existing_drops}")
        
        print(f"Built dataset with {len(df)} observations and {len(df.columns)} features")
        return df
    
    def _create_team_observation(
        self,
        game: Dict[str, Any],
        is_home: bool,
        sport: str,
        target: str,
    ) -> Dict[str, Any]:
        """Create a single team observation from a game."""
        team_prefix = "home" if is_home else "away"
        opp_prefix = "away" if is_home else "home"
        
        row = {
            "game_id": game["game_id"],
            "season": game["season"],
            "date": game["date"],
            "team": game[f"{team_prefix}_team"],
            "opponent": game[f"{opp_prefix}_team"],
            "is_home": 1 if is_home else 0,
        }
        
        # Add sport-specific features
        if sport == "nba":
            row.update({
                "fg_pct": game.get(f"{team_prefix}_fg_pct", 0),
                "3p_pct": game.get(f"{team_prefix}_3p_pct", 0),
                "rebounds": game.get(f"{team_prefix}_rebounds", 0),
                "assists": game.get(f"{team_prefix}_assists", 0),
                "turnovers": game.get(f"{team_prefix}_turnovers", 0),
                "opp_fg_pct": game.get(f"{opp_prefix}_fg_pct", 0),
                "opp_3p_pct": game.get(f"{opp_prefix}_3p_pct", 0),
                "opp_rebounds": game.get(f"{opp_prefix}_rebounds", 0),
                "opp_assists": game.get(f"{opp_prefix}_assists", 0),
                "opp_turnovers": game.get(f"{opp_prefix}_turnovers", 0),
            })
        elif sport == "nfl":
            row.update({
                "total_yards": game.get(f"{team_prefix}_total_yards", 0),
                "passing_yards": game.get(f"{team_prefix}_passing_yards", 0),
                "rushing_yards": game.get(f"{team_prefix}_rushing_yards", 0),
                "turnovers": game.get(f"{team_prefix}_turnovers", 0),
                "opp_total_yards": game.get(f"{opp_prefix}_total_yards", 0),
                "opp_passing_yards": game.get(f"{opp_prefix}_passing_yards", 0),
                "opp_rushing_yards": game.get(f"{opp_prefix}_rushing_yards", 0),
                "opp_turnovers": game.get(f"{opp_prefix}_turnovers", 0),
            })
        
        # Add target
        team_score = game[f"{team_prefix}_score"]
        opp_score = game[f"{opp_prefix}_score"]
        
        if target == "win":
            row["target"] = 1 if team_score > opp_score else 0
        elif target == "score_diff":
            row["target"] = team_score - opp_score
        else:
            raise ValueError(f"Unknown target: {target}")
        
        return row
    
    def create_time_based_splits(
        self,
        df: pd.DataFrame,
        train_ratio: float = 0.6,
        val_ratio: float = 0.2,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Create time-based train/val/test splits.
        
        Args:
            df: DataFrame with date column
            train_ratio: Fraction of data for training
            val_ratio: Fraction of data for validation
        
        Returns:
            Tuple of (train_df, val_df, test_df)
        """
        print("Creating time-based splits...")
        
        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)
        
        n = len(df)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))
        
        train_df = df.iloc[:train_end].copy()
        val_df = df.iloc[train_end:val_end].copy()
        test_df = df.iloc[val_end:].copy()
        
        print(f"Split sizes: train={len(train_df)}, val={len(val_df)}, test={len(test_df)}")
        
        return train_df, val_df, test_df
    
    def save_dataset(self, df: pd.DataFrame, name: str):
        """Save processed dataset."""
        output_path = self.processed_dir / f"{name}.csv"
        df.to_csv(output_path, index=False)
        print(f"Saved dataset to {output_path}")
