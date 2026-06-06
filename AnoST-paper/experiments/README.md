# AnoST Experiment Artifacts

This directory contains the reproducible experiment artifacts used to update the
implementation section of `AnoST-paper/ICICS.tex`.

## Experiment 1: STT rollback simulation

Script:

```bash
MPLCONFIGDIR=/tmp/matplotlib-anost python3 AnoST-paper/experiments/run_stt_experiments.py
```

What it does:

- Builds deterministic State Transition Tree (STT) batches.
- Uses 2000 transactions per batch.
- Assigns transactions to 600 dependency paths.
- Averages each error-ratio setting over 50 generated batches.
- Applies the paper's path-inclusion and partial-pruning logic.

Outputs:

- `data/stt_partial_rollback.csv`
- `data/challenge_window.csv`
- `figures/challenge_window_duration.png`
- `../window.png`

Paper mapping:

- `data/stt_partial_rollback.csv` maps to Table `STT Partial Rollback Performance`
  in `ICICS.tex`, label `tab:rollback-experiment-new`.
- `data/challenge_window.csv` and `figures/challenge_window_duration.png` map to
  Figure `Challenge Window Duration under Various Optimization Mechanisms`,
  label `fig:time`.
- `../window.png` is the actual figure file included by the paper.

The removed file `figures/stt_partial_rollback.png` is intentionally no longer
generated or kept, because the paper uses the STT rollback data as a table.

## Experiment 2: Local EVM rollback demo

Script:

```bash
bash AnoST-paper/experiments/evm/run_evm_benchmark.sh
```

What it does:

- Starts a local Anvil EVM node.
- Builds and deploys `evm/src/STTRollbackBench.sol` with Foundry.
- Sends real RPC transactions for STT root commitment, path challenges, and
  settlement.
- Measures wall-clock time and gas from actual transaction receipts.

Outputs:

- `data/evm_stt_rollback.csv`

Paper mapping:

- `data/evm_stt_rollback.csv` maps to Table `Local EVM STT Rollback Demo` in
  `ICICS.tex`, label `tab:evm-rollback-demo`.

Current EVM demo results:

| Error Ratio | Challenge Paths | Invalidated TXs | Pass Rate | EVM Time | Total Gas |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5% | 5 | 210 | 89.5% | 6.96 s | 585650 |
| 10% | 8 | 409 | 79.5% | 9.95 s | 798590 |
| 20% | 10 | 745 | 62.7% | 11.87 s | 951930 |

The EVM benchmark is meant as a short demonstration run. It uses representative
challenge-path counts derived from the STT simulator so the full demo completes
within a few tens of seconds.

## Tooling notes

- Python dependencies used by `run_stt_experiments.py`: `matplotlib` and `numpy`.
- EVM dependencies used by `evm/run_evm_benchmark.sh`: `forge`, `anvil`, `cast`,
  `node`, and a local Solidity compiler.
- The EVM script defaults to the local Hardhat cached compiler at:

```text
/home/xwk/.cache/hardhat-nodejs/compilers-v2/linux-amd64/solc-linux-amd64-v0.8.19+commit.7dd6d404
```

Override it with:

```bash
SOLC_PATH=/path/to/solc bash AnoST-paper/experiments/evm/run_evm_benchmark.sh
```

Foundry build outputs under `evm/cache/` and `evm/out/` are ignored by git.
