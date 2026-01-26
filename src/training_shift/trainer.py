"""
Baseline model training with season-shift evaluation.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, List
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    mean_squared_error,
    mean_absolute_error,
    r2_score,
)
import joblib


class BaselineTrainer:
    """Train baseline models with optional feature-drop and season-shift evaluation."""
    
    def __init__(self, model_dir: Path, task: str = "classification"):
        """
        Initialize trainer.
        
        Args:
            model_dir: Directory to save trained models
            task: "classification" or "regression"
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.task = task
        self.model = None
        self.feature_columns = None
    
    def train(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        model_type: str = "rf",
        random_state: int = 42,
    ) -> Dict[str, Any]:
        """
        Train baseline model.
        
        Args:
            train_df: Training data with 'target' column
            val_df: Validation data with 'target' column
            model_type: "rf" (random forest) or "linear"
            random_state: Random seed
        
        Returns:
            Dictionary with training metrics
        """
        print(f"Training {model_type} model for {self.task}...")
        
        # Prepare features
        exclude_cols = ["game_id", "season", "date", "team", "opponent", "target"]
        feature_cols = [c for c in train_df.columns if c not in exclude_cols]
        self.feature_columns = feature_cols
        
        X_train = train_df[feature_cols].values
        y_train = train_df["target"].values
        X_val = val_df[feature_cols].values
        y_val = val_df["target"].values
        
        print(f"Training with {len(feature_cols)} features: {feature_cols}")
        print(f"Training samples: {len(X_train)}, Validation samples: {len(X_val)}")
        
        # Initialize model
        if self.task == "classification":
            if model_type == "rf":
                self.model = RandomForestClassifier(
                    n_estimators=100,
                    max_depth=10,
                    random_state=random_state,
                )
            elif model_type == "linear":
                self.model = LogisticRegression(
                    max_iter=1000,
                    random_state=random_state,
                )
            else:
                raise ValueError(f"Unknown model type: {model_type}")
        else:  # regression
            if model_type == "rf":
                self.model = RandomForestRegressor(
                    n_estimators=100,
                    max_depth=10,
                    random_state=random_state,
                )
            elif model_type == "linear":
                self.model = Ridge(
                    alpha=1.0,
                    random_state=random_state,
                )
            else:
                raise ValueError(f"Unknown model type: {model_type}")
        
        # Train
        self.model.fit(X_train, y_train)
        
        # Evaluate
        train_metrics = self._evaluate(X_train, y_train, "train")
        val_metrics = self._evaluate(X_val, y_val, "val")
        
        results = {
            "model_type": model_type,
            "task": self.task,
            "n_features": len(feature_cols),
            "features": feature_cols,
            **train_metrics,
            **val_metrics,
        }
        
        return results
    
    def _evaluate(self, X: np.ndarray, y: np.ndarray, split: str) -> Dict[str, float]:
        """Evaluate model on data."""
        y_pred = self.model.predict(X)
        
        if self.task == "classification":
            metrics = {
                f"{split}_accuracy": accuracy_score(y, y_pred),
                f"{split}_precision": precision_score(y, y_pred, zero_division=0),
                f"{split}_recall": recall_score(y, y_pred, zero_division=0),
                f"{split}_f1": f1_score(y, y_pred, zero_division=0),
            }
        else:  # regression
            metrics = {
                f"{split}_mse": mean_squared_error(y, y_pred),
                f"{split}_mae": mean_absolute_error(y, y_pred),
                f"{split}_r2": r2_score(y, y_pred),
            }
        
        return metrics
    
    def evaluate_season_shift(
        self,
        test_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Evaluate model on test set with per-season breakdown.
        
        Args:
            test_df: Test data with 'season' and 'target' columns
        
        Returns:
            Dictionary with overall and per-season metrics
        """
        print("Evaluating season shift...")
        
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        X_test = test_df[self.feature_columns].values
        y_test = test_df["target"].values
        
        # Overall metrics
        overall_metrics = self._evaluate(X_test, y_test, "test")
        
        # Per-season metrics
        season_metrics = {}
        for season in sorted(test_df["season"].unique()):
            season_mask = test_df["season"] == season
            X_season = test_df.loc[season_mask, self.feature_columns].values
            y_season = test_df.loc[season_mask, "target"].values
            
            if len(y_season) > 0:
                season_results = self._evaluate(X_season, y_season, season)
                season_metrics[season] = season_results
        
        results = {
            "overall": overall_metrics,
            "by_season": season_metrics,
        }
        
        return results
    
    def save_model(self, name: str):
        """Save trained model."""
        if self.model is None:
            raise ValueError("No model to save. Train a model first.")
        
        model_path = self.model_dir / f"{name}.joblib"
        joblib.dump({
            "model": self.model,
            "feature_columns": self.feature_columns,
            "task": self.task,
        }, model_path)
        print(f"Saved model to {model_path}")
    
    def load_model(self, name: str):
        """Load trained model."""
        model_path = self.model_dir / f"{name}.joblib"
        
        if not model_path.exists():
            raise ValueError(f"Model not found: {model_path}")
        
        data = joblib.load(model_path)
        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        self.task = data["task"]
        print(f"Loaded model from {model_path}")
