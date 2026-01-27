"""
End-to-end integration test for the full training-shift pipeline.
Demonstrates the complete workflow from scraping to evaluation.
"""
import sys
import json
import shutil
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


def test_full_pipeline():
    """Test complete pipeline: scrape -> dataset -> train -> evaluate."""
    
    # Setup temporary directories
    test_data_dir = Path("/tmp/training_shift_test")
    if test_data_dir.exists():
        shutil.rmtree(test_data_dir)
    
    raw_dir = test_data_dir / "raw" / "nba"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    processed_dir = test_data_dir / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    
    model_dir = test_data_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*60)
    print("TESTING FULL PIPELINE")
    print("="*60)
    
    # Step 1: Scrape data
    print("\n1. SCRAPING DATA")
    print("-" * 60)
    scraper = ScraperFactory.get_scraper("nba")
    seasons = ["2021-22", "2022-23"]
    
    for season in seasons:
        games = scraper.scrape_season(season)
        season_file = raw_dir / f"{season}.json"
        with open(season_file, "w") as f:
            json.dump(games, f)
        print(f"✓ Saved {len(games)} games for {season}")
    
    # Step 2: Build dataset
    print("\n2. BUILDING DATASET")
    print("-" * 60)
    builder = DatasetBuilder(test_data_dir)
    
    # Regular dataset
    df = builder.build_team_level_dataset(sport="nba", target="win")
    train_df, val_df, test_df = builder.create_time_based_splits(df)
    
    builder.save_dataset(train_df, "nba_win_train")
    builder.save_dataset(val_df, "nba_win_val")
    builder.save_dataset(test_df, "nba_win_test")
    
    print(f"✓ Created dataset: train={len(train_df)}, val={len(val_df)}, test={len(test_df)}")
    
    # Dataset with feature drop (schema drift)
    df_drop = builder.build_team_level_dataset(
        sport="nba",
        target="win",
        feature_drop=["3p_pct", "assists"]
    )
    train_df_drop, val_df_drop, test_df_drop = builder.create_time_based_splits(df_drop)
    
    builder.save_dataset(train_df_drop, "nba_win_train_drop")
    builder.save_dataset(val_df_drop, "nba_win_val_drop")
    builder.save_dataset(test_df_drop, "nba_win_test_drop")
    
    print(f"✓ Created dataset with feature drop: {len(train_df_drop)} samples")
    
    # Step 3: Train models
    print("\n3. TRAINING MODELS")
    print("-" * 60)
    
    # Train Random Forest
    trainer_rf = BaselineTrainer(model_dir, task="classification")
    results_rf = trainer_rf.train(train_df, val_df, model_type="rf")
    print(f"✓ Random Forest: train_acc={results_rf['train_accuracy']:.3f}, val_acc={results_rf['val_accuracy']:.3f}")
    
    # Train Linear model
    trainer_linear = BaselineTrainer(model_dir, task="classification")
    results_linear = trainer_linear.train(train_df, val_df, model_type="linear")
    print(f"✓ Logistic Regression: train_acc={results_linear['train_accuracy']:.3f}, val_acc={results_linear['val_accuracy']:.3f}")
    
    # Train with feature drop
    trainer_drop = BaselineTrainer(model_dir, task="classification")
    results_drop = trainer_drop.train(train_df_drop, val_df_drop, model_type="rf")
    print(f"✓ RF with feature drop: train_acc={results_drop['train_accuracy']:.3f}, val_acc={results_drop['val_accuracy']:.3f}")
    
    # Step 4: Season-shift evaluation
    print("\n4. SEASON-SHIFT EVALUATION")
    print("-" * 60)
    
    shift_results = trainer_rf.evaluate_season_shift(test_df)
    print(f"✓ Overall test accuracy: {shift_results['overall']['test_accuracy']:.3f}")
    
    for season, metrics in shift_results['by_season'].items():
        acc_key = [k for k in metrics.keys() if 'accuracy' in k][0]
        print(f"✓ Season {season} accuracy: {metrics[acc_key]:.3f}")
    
    # Step 5: Save models
    print("\n5. SAVING MODELS")
    print("-" * 60)
    trainer_rf.save_model("nba_win_rf")
    trainer_linear.save_model("nba_win_linear")
    trainer_drop.save_model("nba_win_rf_drop")
    print("✓ All models saved")
    
    # Step 6: Load and verify model
    print("\n6. LOADING AND VERIFYING MODEL")
    print("-" * 60)
    trainer_verify = BaselineTrainer(model_dir, task="classification")
    trainer_verify.load_model("nba_win_rf")
    print("✓ Model loaded successfully")
    
    # Cleanup
    print("\n7. CLEANUP")
    print("-" * 60)
    shutil.rmtree(test_data_dir)
    print("✓ Temporary files cleaned up")
    
    print("\n" + "="*60)
    print("✓ ALL TESTS PASSED!")
    print("="*60 + "\n")


if __name__ == "__main__":
    test_full_pipeline()
