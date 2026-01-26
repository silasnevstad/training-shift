# training-shift

Experiments on training stability and convergence under structured dataset shift, using multi-season sports data to study the effects of feature availability and distribution changes on ML training dynamics.

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .
```

## Quick Start

The CLI provides three main commands to run end-to-end experiments:

### 1. Scrape Sports Data

Scrape game data for multiple seasons:

```bash
# NBA example
training-shift scrape --sport nba --seasons "2020-21,2021-22,2022-23"

# NFL example
training-shift scrape --sport nfl --seasons "2020,2021,2022"
```

### 2. Build Dataset

Build team-level supervised datasets with time-based splits:

```bash
# Classification task (win prediction)
training-shift build-dataset --sport nba --target win

# Regression task (score differential)
training-shift build-dataset --sport nfl --target score_diff

# With feature drop (schema drift simulation)
training-shift build-dataset --sport nba --target win --feature-drop "3p_pct,assists"
```

### 3. Train Model

Train baseline models with optional season-shift evaluation:

```bash
# Basic training
training-shift train --sport nba --target win --model-type rf

# With season-shift evaluation
training-shift train --sport nba --target win --model-type rf --evaluate-shift

# With feature drop (must match dataset)
training-shift train --sport nba --target win --feature-drop "3p_pct,assists" --evaluate-shift
```

## Full Pipeline Example

Run a complete experiment from scratch:

```bash
# 1. Scrape data
training-shift scrape --sport nba --seasons "2019-20,2020-21,2021-22,2022-23"

# 2. Build dataset
training-shift build-dataset --sport nba --target win --train-ratio 0.6 --val-ratio 0.2

# 3. Train baseline model
training-shift train --sport nba --target win --model-type rf --evaluate-shift

# 4. Experiment with schema drift
training-shift build-dataset --sport nba --target win --feature-drop "3p_pct,assists"
training-shift train --sport nba --target win --feature-drop "3p_pct,assists" --evaluate-shift
```

## Project Structure

```
training-shift/
├── data/
│   ├── scraper/          # Sports data scrapers (ScraperFactory.get_scraper())
│   ├── raw/              # Raw scraped game data
│   └── processed/        # Processed datasets with splits
├── src/
│   └── training_shift/
│       ├── cli.py        # Command-line interface
│       ├── dataset.py    # Dataset building and time-based splits
│       └── trainer.py    # Baseline model training
├── models/               # Trained models
├── tests/                # Tests
└── README.md
```

## Features

- **Sports Scrapers**: Mock NBA/NFL scrapers with realistic game statistics
- **Time-Based Splits**: Chronological train/val/test splits to respect temporal ordering
- **Schema Drift Simulation**: Optional feature-drop to study missing features
- **Season-Shift Evaluation**: Per-season performance breakdown on test set
- **Baseline Models**: Random Forest and Linear models for both classification and regression
- **Minimal & Runnable**: End-to-end pipeline with simple CLI interface

## CLI Reference

### scrape
Scrape sports data for specified seasons.

**Options:**
- `--sport`: Sport to scrape (nba, nfl) [required]
- `--seasons`: Comma-separated list of seasons [required]
- `--output-dir`: Output directory (default: data/raw)

### build-dataset
Build team-level supervised dataset with time-based splits.

**Options:**
- `--sport`: Sport to build dataset for (nba, nfl) [required]
- `--target`: Target variable (win, score_diff) [default: win]
- `--train-ratio`: Fraction of data for training [default: 0.6]
- `--val-ratio`: Fraction of data for validation [default: 0.2]
- `--feature-drop`: Comma-separated features to drop for schema drift
- `--data-dir`: Data directory [default: data]

### train
Train baseline model with optional season-shift evaluation.

**Options:**
- `--sport`: Sport to train model for (nba, nfl) [required]
- `--target`: Target variable (win, score_diff) [default: win]
- `--model-type`: Model type (rf, linear) [default: rf]
- `--feature-drop`: Features dropped during dataset build (must match)
- `--data-dir`: Processed data directory [default: data/processed]
- `--model-dir`: Model output directory [default: models]
- `--evaluate-shift`: Evaluate per-season performance on test set [flag]

## Development

Run tests:
```bash
python tests/test_basic.py
```
