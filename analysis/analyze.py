"""Validate and analyze the recorded buck-converter load test.

All published values originate in ``data/raw/buck_data_new.csv`` or are
explicitly calculated from those measurements. The raw files are never edited.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "raw" / "buck_data_new.csv"
PROCESSED_DIR = ROOT / "data" / "processed"
PLOTS_DIR = ROOT / "plots"

EXPECTED_COLUMNS = [
    "time_s",
    "buck_output_V",
    "load_voltage_V",
    "current_A",
    "load_power_W",
    "shunt_voltage_mV",
    "temp_C",
]

NAVY = "#102A43"
BLUE = "#1976A3"
CYAN = "#38A3A5"
ORANGE = "#E67E22"
RED = "#C44536"
GRAY = "#61758A"
LIGHT = "#E7EEF4"


def load_and_validate(path: Path) -> pd.DataFrame:
    """Load the canonical CSV and fail loudly on malformed measurements."""
    frame = pd.read_csv(path)
    if list(frame.columns) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Unexpected schema. Expected {EXPECTED_COLUMNS}; got {list(frame.columns)}"
        )
    if frame.empty:
        raise ValueError("Dataset is empty")

    frame = frame.apply(pd.to_numeric, errors="raise")
    if frame.isna().any().any():
        raise ValueError("Dataset contains missing values")
    if not frame["time_s"].is_monotonic_increasing:
        raise ValueError("time_s must increase monotonically")
    if frame["time_s"].duplicated().any():
        raise ValueError("time_s must not contain duplicates")
    if (frame.drop(columns="temp_C") < 0).any().any():
        raise ValueError("Electrical measurements and elapsed time must be nonnegative")

    intervals = frame["time_s"].diff().dropna().to_numpy()
    if intervals.size and not np.allclose(intervals, intervals[0]):
        raise ValueError("Sampling interval is not uniform")
    return frame


def derive(frame: pd.DataFrame) -> pd.DataFrame:
    """Add transparent calculations without altering measured columns."""
    result = frame.copy()
    result["voltage_drop_V"] = result["buck_output_V"] - result["load_voltage_V"]
    result["calculated_load_power_W"] = result["load_voltage_V"] * result["current_A"]
    result["implied_load_resistance_ohm"] = result["load_voltage_V"] / result["current_A"]
    result["implied_shunt_resistance_ohm"] = (
        result["shunt_voltage_mV"] / 1000.0 / result["current_A"]
    )
    result["power_residual_W"] = (
        result["load_power_W"] - result["calculated_load_power_W"]
    )
    return result


def linear_slope(x: pd.Series, y: pd.Series) -> float:
    """Return the least-squares slope of y versus x."""
    return float(np.polyfit(x.to_numpy(), y.to_numpy(), 1)[0])


def summarize(frame: pd.DataFrame) -> dict[str, float | int]:
    """Calculate the engineering metrics reported in the README."""
    final_window = frame[frame["time_s"] >= frame["time_s"].max() - 120]
    integrate = getattr(np, "trapezoid", None)
    if integrate is None:  # NumPy 1.x compatibility
        integrate = np.trapz
    energy_j = float(integrate(frame["load_power_W"], frame["time_s"]))
    return {
        "sample_count": int(len(frame)),
        "duration_s": float(frame["time_s"].iloc[-1] - frame["time_s"].iloc[0]),
        "sample_interval_s": float(frame["time_s"].diff().dropna().median()),
        "mean_buck_output_V": float(frame["buck_output_V"].mean()),
        "buck_output_peak_to_peak_mV": float(frame["buck_output_V"].max() - frame["buck_output_V"].min()) * 1000,
        "mean_load_voltage_V": float(frame["load_voltage_V"].mean()),
        "load_voltage_peak_to_peak_mV": float(frame["load_voltage_V"].max() - frame["load_voltage_V"].min()) * 1000,
        "mean_current_A": float(frame["current_A"].mean()),
        "current_peak_to_peak_mA": float(frame["current_A"].max() - frame["current_A"].min()) * 1000,
        "mean_load_power_W": float(frame["load_power_W"].mean()),
        "load_power_peak_to_peak_mW": float(frame["load_power_W"].max() - frame["load_power_W"].min()) * 1000,
        "mean_voltage_drop_mV": float(frame["voltage_drop_V"].mean()) * 1000,
        "mean_implied_load_resistance_ohm": float(frame["implied_load_resistance_ohm"].mean()),
        "mean_implied_shunt_resistance_ohm": float(frame["implied_shunt_resistance_ohm"].mean()),
        "max_abs_power_residual_mW": float(frame["power_residual_W"].abs().max()) * 1000,
        "load_energy_J": energy_j,
        "load_energy_Wh": energy_j / 3600.0,
        "initial_temperature_C": float(frame["temp_C"].iloc[0]),
        "final_temperature_C": float(frame["temp_C"].iloc[-1]),
        "temperature_rise_C": float(frame["temp_C"].iloc[-1] - frame["temp_C"].iloc[0]),
        "final_2min_temperature_slope_C_per_min": linear_slope(
            final_window["time_s"], final_window["temp_C"]
        ) * 60.0,
    }


def quality_checks(frame: pd.DataFrame) -> dict[str, bool]:
    """Run consistency checks that can be evaluated from the supplied data."""
    return {
        "schema_exact": list(frame.columns[: len(EXPECTED_COLUMNS)]) == EXPECTED_COLUMNS,
        "121_complete_samples": len(frame) == 121 and not frame.isna().any().any(),
        "uniform_5_second_cadence": np.allclose(frame["time_s"].diff().dropna(), 5.0),
        "power_matches_voltage_times_current_within_5_mW": bool(
            frame["power_residual_W"].abs().max() <= 0.005
        ),
        "voltage_drop_matches_shunt_reading_within_1_mV": bool(
            np.allclose(frame["voltage_drop_V"] * 1000, frame["shunt_voltage_mV"], atol=1.0)
        ),
    }


def configure_plots() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#A9B8C6",
            "axes.labelcolor": NAVY,
            "axes.titlecolor": NAVY,
            "axes.titleweight": "bold",
            "axes.grid": True,
            "grid.color": "#DCE5EC",
            "grid.linewidth": 0.8,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "legend.frameon": False,
            "xtick.color": GRAY,
            "ytick.color": GRAY,
        }
    )


def save_figure(fig: plt.Figure, filename: str) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / filename, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_electrical(frame: pd.DataFrame) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 7.2), sharex=True)
    axes[0].plot(frame["time_s"], frame["buck_output_V"], color=BLUE, lw=2, label="Buck output")
    axes[0].plot(frame["time_s"], frame["load_voltage_V"], color=ORANGE, lw=2, label="Load voltage")
    axes[0].set_ylabel("Voltage (V)")
    axes[0].legend(ncol=2)
    axes[1].plot(frame["time_s"], frame["current_A"], color=CYAN, lw=2)
    axes[1].set_ylabel("Current (A)")
    axes[2].plot(frame["time_s"], frame["load_power_W"], color=NAVY, lw=2)
    axes[2].set_ylabel("Power (W)")
    axes[2].set_xlabel("Elapsed time (s)")
    fig.suptitle("Measured Electrical Stability - 10 Minute Load Test", color=NAVY, fontweight="bold")
    save_figure(fig, "electrical_stability.png")


def plot_thermal(frame: pd.DataFrame, metrics: dict[str, float | int]) -> None:
    fig, ax = plt.subplots(figsize=(9.0, 4.8))
    ax.plot(frame["time_s"] / 60, frame["temp_C"], color=RED, lw=2.5)
    ax.fill_between(frame["time_s"] / 60, frame["temp_C"].iloc[0], frame["temp_C"], color=RED, alpha=0.12)
    ax.scatter([0, 10], [frame["temp_C"].iloc[0], frame["temp_C"].iloc[-1]], color=RED, zorder=3)
    ax.text(
        0.98,
        0.08,
        f"Measured rise: {metrics['temperature_rise_C']:.1f} °C\nFinal 2 min slope: {metrics['final_2min_temperature_slope_C_per_min']:.2f} °C/min",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        color=NAVY,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "white", "edgecolor": LIGHT},
    )
    ax.set_title("Measured Load Temperature Response")
    ax.set_xlabel("Elapsed time (min)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_xlim(0, 10)
    save_figure(fig, "thermal_response.png")


def plot_consistency(frame: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.5))
    axes[0].scatter(frame["load_voltage_V"] * frame["current_A"], frame["load_power_W"], s=24, color=BLUE, alpha=0.75)
    limits = [frame["load_power_W"].min() - 0.002, frame["load_power_W"].max() + 0.002]
    axes[0].plot(limits, limits, color=GRAY, ls="--", lw=1.5, label="1:1 reference")
    axes[0].set_xlim(limits)
    axes[0].set_ylim(limits)
    axes[0].set_xlabel("Calculated V x I (W)")
    axes[0].set_ylabel("Recorded load power (W)")
    axes[0].set_title("Power-channel consistency")
    axes[0].legend()

    axes[1].scatter(frame["shunt_voltage_mV"], frame["voltage_drop_V"] * 1000, s=24, color=ORANGE, alpha=0.75)
    shunt_limits = [frame["shunt_voltage_mV"].min() - 0.02, frame["shunt_voltage_mV"].max() + 0.02]
    axes[1].plot(shunt_limits, shunt_limits, color=GRAY, ls="--", lw=1.5, label="1:1 reference")
    axes[1].set_xlim(shunt_limits)
    axes[1].set_ylim(shunt_limits)
    axes[1].set_xlabel("Recorded shunt voltage (mV)")
    axes[1].set_ylabel("Buck-to-load voltage drop (mV)")
    axes[1].set_title("Voltage-channel consistency")
    axes[1].legend()
    save_figure(fig, "measurement_consistency.png")


def plot_dashboard(frame: pd.DataFrame, metrics: dict[str, float | int]) -> None:
    fig = plt.figure(figsize=(12, 7.2))
    grid = fig.add_gridspec(2, 3, height_ratios=[0.7, 2.2])
    cards = [
        ("MEAN LOAD POWER", f"{metrics['mean_load_power_W']:.3f} W", f"{metrics['load_energy_Wh']:.3f} Wh delivered"),
        ("ELECTRICAL STABILITY", f"{metrics['load_voltage_peak_to_peak_mV']:.1f} mV p-p", f"{metrics['current_peak_to_peak_mA']:.1f} mA current p-p"),
        ("THERMAL RESPONSE", f"+{metrics['temperature_rise_C']:.1f} °C", f"{metrics['initial_temperature_C']:.1f} to {metrics['final_temperature_C']:.1f} °C"),
    ]
    for index, (title, value, detail) in enumerate(cards):
        ax = fig.add_subplot(grid[0, index])
        ax.axis("off")
        ax.text(0.5, 0.77, title, ha="center", color=GRAY, fontsize=9, fontweight="bold")
        ax.text(0.5, 0.44, value, ha="center", color=NAVY, fontsize=20, fontweight="bold")
        ax.text(0.5, 0.15, detail, ha="center", color=GRAY, fontsize=9)
        ax.add_patch(plt.Rectangle((0.02, 0.02), 0.96, 0.94, transform=ax.transAxes, fill=False, edgecolor=LIGHT, linewidth=1.2))

    ax_e = fig.add_subplot(grid[1, :2])
    ax_e.plot(frame["time_s"] / 60, frame["load_power_W"], color=NAVY, lw=2.2)
    ax_e.set_title("Load power remained tightly controlled")
    ax_e.set_xlabel("Elapsed time (min)")
    ax_e.set_ylabel("Measured power (W)")
    ax_e.set_xlim(0, 10)

    ax_t = fig.add_subplot(grid[1, 2])
    ax_t.plot(frame["time_s"] / 60, frame["temp_C"], color=RED, lw=2.2)
    ax_t.fill_between(frame["time_s"] / 60, frame["temp_C"].iloc[0], frame["temp_C"], color=RED, alpha=0.12)
    ax_t.set_title("Temperature continued rising")
    ax_t.set_xlabel("Elapsed time (min)")
    ax_t.set_ylabel("Temperature (°C)")
    ax_t.set_xlim(0, 10)
    fig.suptitle("Empirical Buck-Converter Characterization", color=NAVY, fontsize=16, fontweight="bold", y=1.01)
    save_figure(fig, "results_dashboard.png")


def write_outputs(frame: pd.DataFrame, metrics: dict[str, float | int], checks: dict[str, bool]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(PROCESSED_DIR / "derived_measurements.csv", index=False, float_format="%.6f")
    pd.DataFrame(
        [{"metric": key, "value": value} for key, value in metrics.items()]
    ).to_csv(PROCESSED_DIR / "summary.csv", index=False)
    (PROCESSED_DIR / "summary.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (PROCESSED_DIR / "quality_checks.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")


def run(input_path: Path = DEFAULT_INPUT) -> tuple[pd.DataFrame, dict[str, float | int], dict[str, bool]]:
    measured = load_and_validate(input_path)
    derived = derive(measured)
    metrics = summarize(derived)
    checks = quality_checks(derived)
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"Data-quality checks failed: {failed}")
    configure_plots()
    plot_electrical(derived)
    plot_thermal(derived, metrics)
    plot_consistency(derived)
    plot_dashboard(derived, metrics)
    write_outputs(derived, metrics, checks)
    return derived, metrics, checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Canonical measurement CSV")
    args = parser.parse_args()
    _, metrics, checks = run(args.input)
    print(json.dumps({"metrics": metrics, "quality_checks": checks}, indent=2))


if __name__ == "__main__":
    main()

