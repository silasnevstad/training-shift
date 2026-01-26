"""
CLI for training stability experiments under seasonal dataset shift.
"""
import click
import json
import sys
from pathlib import Path

# Add data directory to path for scraper imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from data.scraper import ScraperFactory
from training_shift.dataset import DatasetBuilder
from training_shift.trainer import BaselineTrainer


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """
    Training stability experiments under seasonal dataset shift.
    
    Run experiments on sports data to study effects of feature availability
    and distribution changes on ML training dynamics.
    """
    pass


@cli.command()
@click.option(
    "--sport",
    type=click.Choice(["nba", "nfl"], case_sensitive=False),
    required=True,
    help="Sport to scrape",
)
@click.option(
    "--seasons",
    required=True,
    help="Comma-separated list of seasons (e.g., '2020-21,2021-22' for NBA or '2020,2021' for NFL)",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    default="data/raw",
    help="Output directory for scraped data",
)
def scrape(sport: str, seasons: str, output_dir: str):
    """
    Scrape sports data for specified seasons.
    
    Examples:
        training-shift scrape --sport nba --seasons "2020-21,2021-22,2022-23"
        training-shift scrape --sport nfl --seasons "2020,2021,2022"
    """
    sport = sport.lower()
    season_list = [s.strip() for s in seasons.split(",")]
    
    click.echo(f"Scraping {sport.upper()} data for {len(season_list)} seasons...")
    
    # Get scraper
    try:
        scraper = ScraperFactory.get_scraper(sport)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    
    # Create output directory
    output_path = Path(output_dir) / sport
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Scrape each season
    for season in season_list:
        click.echo(f"\n{'='*60}")
        click.echo(f"Scraping season: {season}")
        click.echo('='*60)
        
        try:
            games = scraper.scrape_season(season)
            
            # Save to JSON
            season_file = output_path / f"{season.replace('/', '-')}.json"
            with open(season_file, "w") as f:
                json.dump(games, f, indent=2)
            
            click.echo(f"✓ Saved {len(games)} games to {season_file}")
        
        except Exception as e:
            click.echo(f"✗ Error scraping season {season}: {e}", err=True)
    
    click.echo(f"\n{'='*60}")
    click.echo(f"✓ Scraping complete! Data saved to {output_path}")
    click.echo('='*60)


@cli.command()
@click.option(
    "--sport",
    type=click.Choice(["nba", "nfl"], case_sensitive=False),
    required=True,
    help="Sport to build dataset for",
)
@click.option(
    "--target",
    type=click.Choice(["win", "score_diff"]),
    default="win",
    help="Target variable (win=classification, score_diff=regression)",
)
@click.option(
    "--train-ratio",
    type=float,
    default=0.6,
    help="Fraction of data for training",
)
@click.option(
    "--val-ratio",
    type=float,
    default=0.2,
    help="Fraction of data for validation",
)
@click.option(
    "--feature-drop",
    help="Comma-separated features to drop (for schema drift simulation)",
)
@click.option(
    "--data-dir",
    type=click.Path(),
    default="data",
    help="Data directory",
)
def build_dataset(
    sport: str,
    target: str,
    train_ratio: float,
    val_ratio: float,
    feature_drop: str,
    data_dir: str,
):
    """
    Build team-level supervised dataset with time-based splits.
    
    Examples:
        training-shift build-dataset --sport nba --target win
        training-shift build-dataset --sport nfl --target score_diff --feature-drop "passing_yards,rushing_yards"
    """
    sport = sport.lower()
    
    click.echo(f"Building {sport.upper()} dataset...")
    click.echo(f"Target: {target}")
    click.echo(f"Split ratios: train={train_ratio}, val={val_ratio}, test={1-train_ratio-val_ratio}")
    
    # Parse feature drop
    feature_drop_list = None
    if feature_drop:
        feature_drop_list = [f.strip() for f in feature_drop.split(",")]
        click.echo(f"Feature drop (schema drift): {feature_drop_list}")
    
    # Build dataset
    builder = DatasetBuilder(Path(data_dir))
    
    try:
        df = builder.build_team_level_dataset(
            sport=sport,
            target=target,
            feature_drop=feature_drop_list,
        )
        
        # Create time-based splits
        train_df, val_df, test_df = builder.create_time_based_splits(
            df,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
        )
        
        # Save splits
        suffix = f"_drop_{'_'.join(feature_drop_list)}" if feature_drop_list else ""
        builder.save_dataset(train_df, f"{sport}_{target}_train{suffix}")
        builder.save_dataset(val_df, f"{sport}_{target}_val{suffix}")
        builder.save_dataset(test_df, f"{sport}_{target}_test{suffix}")
        
        click.echo(f"\n{'='*60}")
        click.echo("✓ Dataset build complete!")
        click.echo(f"  Train: {len(train_df)} samples")
        click.echo(f"  Val: {len(val_df)} samples")
        click.echo(f"  Test: {len(test_df)} samples")
        click.echo(f"  Features: {len([c for c in df.columns if c not in ['game_id', 'season', 'date', 'team', 'opponent', 'target']])}")
        click.echo('='*60)
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--sport",
    type=click.Choice(["nba", "nfl"], case_sensitive=False),
    required=True,
    help="Sport to train model for",
)
@click.option(
    "--target",
    type=click.Choice(["win", "score_diff"]),
    default="win",
    help="Target variable (win=classification, score_diff=regression)",
)
@click.option(
    "--model-type",
    type=click.Choice(["rf", "linear"]),
    default="rf",
    help="Model type (rf=random forest, linear=logistic/ridge)",
)
@click.option(
    "--feature-drop",
    help="Comma-separated features dropped during dataset build (must match)",
)
@click.option(
    "--data-dir",
    type=click.Path(),
    default="data/processed",
    help="Processed data directory",
)
@click.option(
    "--model-dir",
    type=click.Path(),
    default="models",
    help="Model output directory",
)
@click.option(
    "--evaluate-shift",
    is_flag=True,
    help="Evaluate per-season performance on test set",
)
def train(
    sport: str,
    target: str,
    model_type: str,
    feature_drop: str,
    data_dir: str,
    model_dir: str,
    evaluate_shift: bool,
):
    """
    Train baseline model with optional season-shift evaluation.
    
    Examples:
        training-shift train --sport nba --target win --model-type rf
        training-shift train --sport nfl --target score_diff --model-type linear --evaluate-shift
        training-shift train --sport nba --target win --feature-drop "3p_pct,assists" --evaluate-shift
    """
    sport = sport.lower()
    
    click.echo(f"Training {model_type.upper()} model for {sport.upper()} ({target})...")
    
    # Determine task type
    task = "classification" if target == "win" else "regression"
    
    # Load datasets
    data_path = Path(data_dir)
    suffix = ""
    if feature_drop:
        feature_drop_list = [f.strip() for f in feature_drop.split(",")]
        suffix = f"_drop_{'_'.join(feature_drop_list)}"
    
    try:
        import pandas as pd
        
        train_df = pd.read_csv(data_path / f"{sport}_{target}_train{suffix}.csv")
        val_df = pd.read_csv(data_path / f"{sport}_{target}_val{suffix}.csv")
        test_df = pd.read_csv(data_path / f"{sport}_{target}_test{suffix}.csv")
        
        click.echo(f"Loaded datasets: train={len(train_df)}, val={len(val_df)}, test={len(test_df)}")
    
    except FileNotFoundError as e:
        click.echo(f"Error: Dataset files not found. Run build-dataset first.", err=True)
        click.echo(f"Details: {e}", err=True)
        sys.exit(1)
    
    # Train model
    trainer = BaselineTrainer(Path(model_dir), task=task)
    
    try:
        results = trainer.train(
            train_df=train_df,
            val_df=val_df,
            model_type=model_type,
        )
        
        click.echo(f"\n{'='*60}")
        click.echo("Training Results:")
        click.echo('='*60)
        
        for key, value in results.items():
            if key not in ["features"]:
                if isinstance(value, float):
                    click.echo(f"  {key}: {value:.4f}")
                else:
                    click.echo(f"  {key}: {value}")
        
        # Save model
        model_name = f"{sport}_{target}_{model_type}{suffix}"
        trainer.save_model(model_name)
        
        # Season-shift evaluation
        if evaluate_shift:
            click.echo(f"\n{'='*60}")
            click.echo("Season-Shift Evaluation:")
            click.echo('='*60)
            
            shift_results = trainer.evaluate_season_shift(test_df)
            
            click.echo("\nOverall Test Metrics:")
            for key, value in shift_results["overall"].items():
                click.echo(f"  {key}: {value:.4f}")
            
            click.echo("\nPer-Season Breakdown:")
            for season, metrics in shift_results["by_season"].items():
                click.echo(f"\n  Season {season}:")
                for key, value in metrics.items():
                    metric_name = key.replace(season, "").strip("_")
                    click.echo(f"    {metric_name}: {value:.4f}")
        
        click.echo(f"\n{'='*60}")
        click.echo(f"✓ Training complete! Model saved as '{model_name}'")
        click.echo('='*60)
    
    except Exception as e:
        click.echo(f"Error during training: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    cli()
