#!/usr/bin/env python3
"""
Demo script showing the full training-shift workflow.
Run this to see the complete pipeline in action.
"""

import subprocess
import sys

def run_command(cmd, description):
    """Run a command and print its output."""
    print("\n" + "="*70)
    print(f"🔹 {description}")
    print("="*70)
    print(f"$ {cmd}\n")
    
    result = subprocess.run(cmd, shell=True, capture_output=False, text=True)
    
    if result.returncode != 0:
        print(f"\n❌ Command failed with exit code {result.returncode}")
        sys.exit(1)
    
    return result


def main():
    """Run the complete demo."""
    
    print("\n" + "="*70)
    print("🚀 TRAINING-SHIFT DEMO: Seasonal Dataset Shift Experiments")
    print("="*70)
    
    # 1. Scrape data
    run_command(
        'training-shift scrape --sport nba --seasons "2020-21,2021-22,2022-23"',
        "Step 1: Scraping NBA data for 3 seasons"
    )
    
    # 2. Build baseline dataset
    run_command(
        'training-shift build-dataset --sport nba --target win',
        "Step 2: Building team-level dataset with time-based splits"
    )
    
    # 3. Train baseline model
    run_command(
        'training-shift train --sport nba --target win --model-type rf --evaluate-shift',
        "Step 3: Training Random Forest classifier with season-shift evaluation"
    )
    
    # 4. Build dataset with feature drop (schema drift)
    run_command(
        'training-shift build-dataset --sport nba --target win --feature-drop "3p_pct,assists"',
        "Step 4: Building dataset with schema drift (dropped 3p_pct & assists)"
    )
    
    # 5. Train model with feature drop
    run_command(
        'training-shift train --sport nba --target win --feature-drop "3p_pct,assists" --evaluate-shift',
        "Step 5: Training model with schema drift"
    )
    
    # 6. NFL regression example
    run_command(
        'training-shift scrape --sport nfl --seasons "2021,2022"',
        "Step 6: Scraping NFL data"
    )
    
    run_command(
        'training-shift build-dataset --sport nfl --target score_diff',
        "Step 7: Building NFL regression dataset"
    )
    
    run_command(
        'training-shift train --sport nfl --target score_diff --model-type linear --evaluate-shift',
        "Step 8: Training linear regression model for score prediction"
    )
    
    print("\n" + "="*70)
    print("✅ DEMO COMPLETE!")
    print("="*70)
    print("\n📊 Results:")
    print("  - Scraped data: data/raw/")
    print("  - Processed datasets: data/processed/")
    print("  - Trained models: models/")
    print("\n💡 Try experimenting with different:")
    print("  - Sports (nba, nfl)")
    print("  - Targets (win, score_diff)")
    print("  - Model types (rf, linear)")
    print("  - Feature drops (schema drift simulation)")
    print("\n📖 See README.md for more details\n")


if __name__ == "__main__":
    main()
