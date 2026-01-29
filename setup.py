from setuptools import setup, find_packages

setup(
    name="training-shift",
    version="0.1.0",
    description="Experiments on training stability under seasonal dataset shift",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "click>=8.1.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.3.0",
        "joblib>=1.3.0",
    ],
    entry_points={
        "console_scripts": [
            "training-shift=training_shift.cli:cli",
            "shiftbench=shiftbench.cli:cli",
        ],
    },
)
