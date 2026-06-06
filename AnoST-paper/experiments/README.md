# AnoST 实验说明

本目录保存论文 `AnoST-paper/ICICS.tex` 实验部分用到的可复现实验脚本、数据文件和图像输出。当前包含两类实验：

- STT 部分回滚与挑战窗口的本地确定性模拟实验。
- 基于 Foundry/Anvil 的本地 EVM 真实交易执行实验。

## 1. STT 部分回滚与挑战窗口模拟实验

运行命令：

```bash
MPLCONFIGDIR=/tmp/matplotlib-anost python3 AnoST-paper/experiments/run_stt_experiments.py
```

实验内容：

- 每个 batch 包含 2000 笔交易。
- 交易被分配到 600 条状态依赖路径。
- 每个错误率设置独立生成 50 个 batch，并取平均值。
- 按论文中的 STT DAG 构造、path-inclusion detection 和 partial pruning 逻辑执行。
- 生成 STT 部分回滚表格数据，以及挑战窗口图表数据。

输出位置：

- `AnoST-paper/experiments/data/stt_partial_rollback.csv`
- `AnoST-paper/experiments/data/challenge_window.csv`
- `AnoST-paper/experiments/figures/challenge_window_duration.png`
- `AnoST-paper/window.png`

与论文对应关系：

- `data/stt_partial_rollback.csv` 对应论文中的表格 `STT Partial Rollback Performance`，LaTeX 标签为 `tab:rollback-experiment-new`。
- `data/challenge_window.csv` 对应论文中的图 `Challenge Window Duration under Various Optimization Mechanisms` 的原始数据，LaTeX 标签为 `fig:time`。
- `figures/challenge_window_duration.png` 是挑战窗口图的实验目录备份。
- `AnoST-paper/window.png` 是论文正文通过 `\includegraphics{window.png}` 实际引用的图片。

说明：

- `figures/stt_partial_rollback.png` 已经删除，并且脚本不再生成它。STT 部分回滚结果现在只以论文表格形式呈现。

## 2. 本地 EVM STT 回滚演示实验

运行命令：

```bash
bash AnoST-paper/experiments/evm/run_evm_benchmark.sh
```

实验内容：

- 启动本地 Anvil EVM 节点。
- 使用 Foundry 编译并部署 `evm/src/STTRollbackBench.sol`。
- 通过真实 RPC 交易执行 STT root commit、path challenge 和 settle 流程。
- 从交易 receipt 中统计 gas。
- 统计每组实验的 wall-clock time，用于演示环境下的端到端执行时间。

输出位置：

- `AnoST-paper/experiments/data/evm_stt_rollback.csv`

与论文对应关系：

- `data/evm_stt_rollback.csv` 对应论文中的表格 `Local EVM STT Rollback Demo`，LaTeX 标签为 `tab:evm-rollback-demo`。

当前 EVM 演示结果：

| 错误率 | Challenge Paths | Invalidated TXs | Pass Rate | EVM Time | Total Gas |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5% | 5 | 210 | 89.5% | 6.96 s | 585650 |
| 10% | 8 | 409 | 79.5% | 9.95 s | 798590 |
| 20% | 10 | 745 | 62.7% | 11.87 s | 951930 |

说明：

- EVM 实验是演示型真实本地 EVM 执行实验，不是 Python 纯模拟。
- 挑战路径数量来自 STT 模拟实验中的代表性结果，因此完整 EVM 演示可以控制在几十秒内完成。
- 该实验会生成 Foundry 构建目录 `evm/cache/` 和 `evm/out/`，这两个目录已通过 `evm/.gitignore` 忽略，不需要提交。

## 依赖环境

STT 模拟实验需要：

- Python 3
- `matplotlib`
- `numpy`

EVM 演示实验需要：

- `forge`
- `anvil`
- `cast`
- `node`
- Solidity 编译器

默认 Solidity 编译器路径为：

```text
/home/xwk/.cache/hardhat-nodejs/compilers-v2/linux-amd64/solc-linux-amd64-v0.8.19+commit.7dd6d404
```

如果本机 Solidity 编译器路径不同，可以通过 `SOLC_PATH` 覆盖：

```bash
SOLC_PATH=/path/to/solc bash AnoST-paper/experiments/evm/run_evm_benchmark.sh
```

## 论文中已呈现的内容

论文 `AnoST-paper/ICICS.tex` 中已经呈现以下实验结果：

- 表 `STT Partial Rollback Performance`：来自 `data/stt_partial_rollback.csv`。
- 表 `Local EVM STT Rollback Demo`：来自 `data/evm_stt_rollback.csv`。
- 图 `Challenge Window Duration under Various Optimization Mechanisms`：来自 `data/challenge_window.csv`，实际引用图片为 `AnoST-paper/window.png`。
