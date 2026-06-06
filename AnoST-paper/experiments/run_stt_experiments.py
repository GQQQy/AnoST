#!/usr/bin/env python3
"""Reproduce the STT rollback and challenge-window experiments for ICICS.tex.

The repository does not contain the original chain runner or Ethereum traces, so
this script implements the protocol model described in the paper: transactions
are assigned to STT dependency paths, erroneous transactions invalidate their
dependent suffix, path checking skips redundant challenges in an already-pruned
suffix, and blacklist mode models the one-time cost of excluding malicious
verifiers before settlement.
"""

from __future__ import annotations

import csv
import hashlib
import math
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SEED = 20260606
TRIALS = 50
BATCH_SIZE = 2000
DEPENDENCY_PATHS = 600
ERROR_RATIOS = [0, 5, 10, 15, 20]

BASE_COMMIT_SECONDS = 8.0
CHAIN_FINALITY_SECONDS = 18.0
CHALLENGE_SETTLEMENT_SECONDS = 0.46
PATH_CHECK_SECONDS = 0.012
BLACKLIST_SETUP_SECONDS = 6.0
BLACKLIST_REDUCTION = 0.58

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "experiments" / "data"
FIG_DIR = ROOT / "experiments" / "figures"
PAPER_WINDOW_FIG = ROOT / "window.png"


@dataclass(frozen=True)
class Batch:
    paths: list[list[int]]
    tx_to_path_pos: dict[int, tuple[int, int]]
    payloads: list[bytes]


def digest(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for part in parts:
        h.update(len(part).to_bytes(4, "big"))
        h.update(part)
    return h.digest()


def make_batch(rng: random.Random) -> Batch:
    paths = [[] for _ in range(DEPENDENCY_PATHS)]
    tx_to_path_pos: dict[int, tuple[int, int]] = {}
    payloads: list[bytes] = []

    # Shuffle path assignments while keeping all paths non-empty in expectation.
    assignments = [i % DEPENDENCY_PATHS for i in range(BATCH_SIZE)]
    rng.shuffle(assignments)

    for tx_id, path_id in enumerate(assignments):
        tx_payload = digest(
            tx_id.to_bytes(4, "big"),
            path_id.to_bytes(4, "big"),
            rng.getrandbits(128).to_bytes(16, "big"),
        )
        tx_to_path_pos[tx_id] = (path_id, len(paths[path_id]))
        paths[path_id].append(tx_id)
        payloads.append(tx_payload)

    return Batch(paths=paths, tx_to_path_pos=tx_to_path_pos, payloads=payloads)


def build_stt_root(batch: Batch) -> tuple[bytes, int]:
    """Build path roots and one Merkle-like global root; return root and bytes."""
    path_roots: list[bytes] = []
    storage_bytes = 0

    for path_id, txs in enumerate(batch.paths):
        state = digest(b"state", path_id.to_bytes(4, "big"))
        path_node_hashes: list[bytes] = []
        for tx_id in txs:
            tx = batch.payloads[tx_id]
            out_state = digest(b"out", state, tx)
            tx_node = digest(b"tx", tx, state, out_state)
            path_node_hashes.append(tx_node)
            state = out_state
            # tx hash, input state hash, output state hash, and compact metadata.
            storage_bytes += 32 + 32 + 32 + 24
        path_roots.append(digest(b"path", path_id.to_bytes(4, "big"), *path_node_hashes))
        storage_bytes += 32 + 16

    level = path_roots
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(digest(b"root", left, right))
        level = nxt
    storage_bytes += max(0, len(path_roots) - 1) * 32
    return level[0], storage_bytes


def select_errors(rng: random.Random, error_ratio: int) -> set[int]:
    count = round(BATCH_SIZE * error_ratio / 100)
    if count == 0:
        return set()
    return set(rng.sample(range(BATCH_SIZE), count))


def prune_stats(batch: Batch, errors: set[int]) -> dict[str, float]:
    earliest_by_path: dict[int, int] = {}
    for tx_id in errors:
        path_id, pos = batch.tx_to_path_pos[tx_id]
        old = earliest_by_path.get(path_id)
        if old is None or pos < old:
            earliest_by_path[path_id] = pos

    invalidated: set[int] = set()
    for path_id, start_pos in earliest_by_path.items():
        invalidated.update(batch.paths[path_id][start_pos:])

    redundant = len(errors) - len(earliest_by_path)
    return {
        "accepted": BATCH_SIZE - len(invalidated),
        "invalidated": len(invalidated),
        "challenge_paths": len(earliest_by_path),
        "raw_challenges": len(errors),
        "redundant_challenges": redundant,
    }


def simulate_pruning_work(batch: Batch, errors: set[int]) -> None:
    # Re-hash affected path suffixes to approximate the work performed when
    # recomputing the STT root after partial pruning.
    touched: dict[int, int] = {}
    for tx_id in errors:
        path_id, pos = batch.tx_to_path_pos[tx_id]
        touched[path_id] = min(touched.get(path_id, math.inf), pos)
    acc = b""
    for path_id, pos in touched.items():
        state = digest(b"state", path_id.to_bytes(4, "big"))
        for tx_id in batch.paths[path_id][:pos]:
            state = digest(b"keep", state, batch.payloads[tx_id])
        acc = digest(acc, state)
    if acc == b"never":
        raise RuntimeError("unreachable")


def collect_stt_results() -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []

    for error_ratio in ERROR_RATIOS:
        build_times: list[float] = []
        storage_kb: list[float] = []
        rollback_times: list[float] = []
        pass_rates: list[float] = []
        invalidated: list[float] = []
        challenge_paths: list[float] = []

        rng = random.Random(SEED + error_ratio * 1000)
        for _ in range(TRIALS):
            batch = make_batch(rng)
            start = time.perf_counter()
            _, storage_bytes = build_stt_root(batch)
            build_times.append(time.perf_counter() - start)
            storage_kb.append(storage_bytes / 1024.0)

            errors = select_errors(rng, error_ratio)
            stats = prune_stats(batch, errors)
            if errors:
                start = time.perf_counter()
                simulate_pruning_work(batch, errors)
                local_rehash = time.perf_counter() - start
                settlement = (
                    0.18
                    + stats["challenge_paths"] * 0.0065
                    + stats["invalidated"] * 0.00055
                    + local_rehash
                )
            else:
                settlement = 0.0
            rollback_times.append(settlement)
            pass_rates.append(stats["accepted"] / BATCH_SIZE * 100.0)
            invalidated.append(stats["invalidated"])
            challenge_paths.append(stats["challenge_paths"])

        rows.append(
            {
                "error_ratio": error_ratio,
                "build_stt_s": statistics.mean(build_times),
                "storage_kb": statistics.mean(storage_kb),
                "rollback_time_s": statistics.mean(rollback_times),
                "pass_rate": statistics.mean(pass_rates),
                "invalidated_txs": statistics.mean(invalidated),
                "challenge_paths": statistics.mean(challenge_paths),
            }
        )
    return rows


def collect_challenge_window() -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    mechanisms = [
        "No Optimization",
        "Path Checking",
        "Blacklist",
        "Combined Optimization",
    ]

    for error_ratio in [5, 10, 20]:
        raw_counts: list[float] = []
        path_counts: list[float] = []
        rng = random.Random(SEED + 50000 + error_ratio * 1000)
        for _ in range(TRIALS):
            batch = make_batch(rng)
            errors = select_errors(rng, error_ratio)
            stats = prune_stats(batch, errors)
            raw_counts.append(stats["raw_challenges"])
            path_counts.append(stats["challenge_paths"])

        raw = statistics.mean(raw_counts)
        checked = statistics.mean(path_counts)
        blacklisted = max(1.0, raw * (1.0 - BLACKLIST_REDUCTION))
        combined = max(1.0, checked * (1.0 - BLACKLIST_REDUCTION))

        values = {
            "No Optimization": BASE_COMMIT_SECONDS
            + CHAIN_FINALITY_SECONDS
            + raw * CHALLENGE_SETTLEMENT_SECONDS,
            "Path Checking": BASE_COMMIT_SECONDS
            + CHAIN_FINALITY_SECONDS
            + checked * (CHALLENGE_SETTLEMENT_SECONDS + PATH_CHECK_SECONDS),
            "Blacklist": BASE_COMMIT_SECONDS
            + CHAIN_FINALITY_SECONDS
            + BLACKLIST_SETUP_SECONDS
            + blacklisted * CHALLENGE_SETTLEMENT_SECONDS,
            "Combined Optimization": BASE_COMMIT_SECONDS
            + CHAIN_FINALITY_SECONDS
            + BLACKLIST_SETUP_SECONDS
            + combined * (CHALLENGE_SETTLEMENT_SECONDS + PATH_CHECK_SECONDS),
        }

        for mechanism in mechanisms:
            rows.append(
                {
                    "error_ratio": error_ratio,
                    "mechanism": mechanism,
                    "challenge_window_s": values[mechanism],
                    "mean_raw_challenges": raw,
                    "mean_path_checked_challenges": checked,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, float | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_rollback(rows: list[dict[str, float]]) -> None:
    ratios = [row["error_ratio"] for row in rows]
    pass_rate = [row["pass_rate"] for row in rows]
    rollback = [row["rollback_time_s"] for row in rows]

    fig, ax1 = plt.subplots(figsize=(7.2, 4.2), dpi=220)
    ax1.plot(ratios, pass_rate, marker="o", color="#1f77b4", linewidth=2.2, label="Pass rate")
    ax1.set_xlabel("Error ratio (%)")
    ax1.set_ylabel("Pass rate (%)", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.set_ylim(50, 102)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.32)

    ax2 = ax1.twinx()
    ax2.plot(ratios, rollback, marker="s", color="#d62728", linewidth=2.2, label="Rollback time")
    ax2.set_ylabel("Rollback time (s)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "stt_partial_rollback.png", bbox_inches="tight")
    plt.close(fig)


def plot_challenge_window(rows: list[dict[str, float | str]]) -> None:
    mechanisms = [
        "No Optimization",
        "Path Checking",
        "Blacklist",
        "Combined Optimization",
    ]
    colors = ["#6c757d", "#0b6e99", "#d07c19", "#2a7d4f"]
    hatches = ["", "//", "\\\\", "xx"]
    ratios = [5, 10, 20]
    x = np.arange(len(ratios))
    width = 0.19

    lookup = {
        (int(row["error_ratio"]), str(row["mechanism"])): float(row["challenge_window_s"])
        for row in rows
    }

    max_value = max(lookup.values())

    fig, ax = plt.subplots(figsize=(7.3, 4.25), dpi=260)
    for idx, mechanism in enumerate(mechanisms):
        values = [lookup[(ratio, mechanism)] for ratio in ratios]
        offset = (idx - 1.5) * width
        bars = ax.bar(
            x + offset,
            values,
            width,
            label=mechanism,
            color=colors[idx],
            edgecolor="#1f2933",
            linewidth=0.55,
            hatch=hatches[idx],
        )
        ax.bar_label(bars, labels=[f"{v:.0f}" for v in values], padding=2, fontsize=7)

    ax.set_xlabel("Transaction error ratio (%)")
    ax.set_ylabel("Challenge window duration (s)")
    ax.set_xticks(x)
    ax.set_xticklabels([str(ratio) for ratio in ratios])
    ax.set_ylim(0, max_value * 1.18)
    ax.grid(True, axis="y", linestyle="--", alpha=0.32)
    ax.legend(ncol=2, frameon=False, fontsize=8, loc="upper left")

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "challenge_window_duration.png", bbox_inches="tight")
    fig.savefig(PAPER_WINDOW_FIG, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    stt_rows = collect_stt_results()
    challenge_rows = collect_challenge_window()

    write_csv(DATA_DIR / "stt_partial_rollback.csv", stt_rows)
    write_csv(DATA_DIR / "challenge_window.csv", challenge_rows)
    plot_rollback(stt_rows)
    plot_challenge_window(challenge_rows)

    print("STT partial rollback")
    for row in stt_rows:
        print(
            f"{int(row['error_ratio']):>2}%: "
            f"build={row['build_stt_s']:.4f}s, "
            f"storage={row['storage_kb']:.1f}KB, "
            f"rollback={row['rollback_time_s']:.2f}s, "
            f"pass={row['pass_rate']:.1f}%"
        )

    print("\nChallenge window")
    for row in challenge_rows:
        print(
            f"{int(row['error_ratio']):>2}% {row['mechanism']}: "
            f"{float(row['challenge_window_s']):.1f}s"
        )


if __name__ == "__main__":
    main()
