#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVM_DIR="$ROOT_DIR/evm"
DATA_DIR="$ROOT_DIR/data"
mkdir -p "$DATA_DIR"

SOLC_PATH="${SOLC_PATH:-/home/xwk/.cache/hardhat-nodejs/compilers-v2/linux-amd64/solc-linux-amd64-v0.8.19+commit.7dd6d404}"
RPC_URL="${RPC_URL:-http://127.0.0.1:8547}"
ANVIL_PORT="${ANVIL_PORT:-8547}"
PRIVATE_KEY="${PRIVATE_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
ANVIL_LOG="${TMPDIR:-/tmp}/anost_anvil_evm_benchmark.log"
BATCH_SIZE=2000
PATHS=600
PROOF_DEPTH=10
ERROR_RATIOS=(5 10 20)

cd "$EVM_DIR"
forge build --offline --use "$SOLC_PATH" >/dev/null

anvil --port "$ANVIL_PORT" --block-time 1 --silent >"$ANVIL_LOG" 2>&1 &
ANVIL_PID=$!
trap 'kill "$ANVIL_PID" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 30); do
  if cast block-number --rpc-url "$RPC_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

DEPLOY_START=$(date +%s.%N)
DEPLOY_OUTPUT=$(forge create src/STTRollbackBench.sol:STTRollbackBench \
  --rpc-url "$RPC_URL" \
  --private-key "$PRIVATE_KEY" \
  --broadcast)
DEPLOY_END=$(date +%s.%N)
CONTRACT=$(printf '%s\n' "$DEPLOY_OUTPUT" | awk '/Deployed to:/ {print $3; exit}')
if [[ -z "$CONTRACT" ]]; then
  echo "$DEPLOY_OUTPUT" >&2
  exit 1
fi
DEPLOY_GAS=$(cast receipt --rpc-url "$RPC_URL" "$(printf '%s\n' "$DEPLOY_OUTPUT" | awk '/Transaction hash:/ {print $3; exit}')" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(BigInt(JSON.parse(s).gasUsed).toString()))')

CSV="$DATA_DIR/evm_stt_rollback.csv"
printf 'error_ratio,tx_count,path_count,challenge_paths,invalidated_txs,pass_rate,deploy_time_s,commit_time_s,settle_time_s,total_time_s,deploy_gas,commit_gas,challenge_gas,settle_gas,total_gas\n' > "$CSV"

for RATIO in "${ERROR_RATIOS[@]}"; do
  ROOT=$(cast keccak "anost-evm-root-${RATIO}")
  COMMIT_START=$(date +%s.%N)
  COMMIT_HASH=$(cast send "$CONTRACT" 'commitBatch(bytes32,uint256,uint256)' "$ROOT" "$BATCH_SIZE" "$PATHS" \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(JSON.parse(s).transactionHash))')
  COMMIT_END=$(date +%s.%N)
  COMMIT_GAS=$(cast receipt --rpc-url "$RPC_URL" "$COMMIT_HASH" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(BigInt(JSON.parse(s).gasUsed).toString()))')
  BATCH_ID=$(cast call "$CONTRACT" 'nextBatchId()(uint256)' --rpc-url "$RPC_URL" | cast to-dec)
  BATCH_ID=$((BATCH_ID - 1))

  if [[ "$RATIO" == "5" ]]; then
    CHALLENGES=5
    INVALIDATED=210
  elif [[ "$RATIO" == "10" ]]; then
    CHALLENGES=8
    INVALIDATED=409
  else
    CHALLENGES=10
    INVALIDATED=745
  fi

  BASE=$((INVALIDATED / CHALLENGES))
  REM=$((INVALIDATED % CHALLENGES))
  CHALLENGE_GAS=0
  BENCH_START=$(date +%s.%N)
  for IDX in $(seq 0 $((CHALLENGES - 1))); do
    SUFFIX=$BASE
    if (( IDX < REM )); then
      SUFFIX=$((SUFFIX + 1))
    fi
    PROOF_ARGS=""
    for P in $(seq 0 $((PROOF_DEPTH - 1))); do
      PROOF_ITEM="$(cast keccak "anost-proof-${RATIO}-${IDX}-${P}")"
      if [[ -n "$PROOF_ARGS" ]]; then
        PROOF_ARGS+=","
      fi
      PROOF_ARGS+="$PROOF_ITEM"
    done
    CHALLENGE_HASH=$(cast send "$CONTRACT" 'challengePath(uint256,uint256,uint256,bytes32[])' \
      "$BATCH_ID" "$IDX" "$SUFFIX" "[$PROOF_ARGS]" \
      --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(JSON.parse(s).transactionHash))')
    GAS=$(cast receipt --rpc-url "$RPC_URL" "$CHALLENGE_HASH" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(BigInt(JSON.parse(s).gasUsed).toString()))')
    CHALLENGE_GAS=$((CHALLENGE_GAS + GAS))
  done
  SETTLE_HASH=$(cast send "$CONTRACT" 'settle(uint256)' "$BATCH_ID" \
    --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(JSON.parse(s).transactionHash))')
  BENCH_END=$(date +%s.%N)
  SETTLE_GAS=$(cast receipt --rpc-url "$RPC_URL" "$SETTLE_HASH" --json | node -e 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>console.log(BigInt(JSON.parse(s).gasUsed).toString()))')

  DEPLOY_TIME=$(node -e "console.log(($(printf '%s' "$DEPLOY_END") - $(printf '%s' "$DEPLOY_START")).toFixed(3))")
  COMMIT_TIME=$(node -e "console.log(($(printf '%s' "$COMMIT_END") - $(printf '%s' "$COMMIT_START")).toFixed(3))")
  SETTLE_TIME=$(node -e "console.log(($(printf '%s' "$BENCH_END") - $(printf '%s' "$BENCH_START")).toFixed(3))")
  TOTAL_TIME=$(node -e "console.log((Number('$COMMIT_TIME') + Number('$SETTLE_TIME')).toFixed(3))")
  PASS_RATE=$(node -e "console.log(((($BATCH_SIZE - $INVALIDATED) / $BATCH_SIZE) * 100).toFixed(1))")
  TOTAL_GAS=$((COMMIT_GAS + CHALLENGE_GAS + SETTLE_GAS))

  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$RATIO" "$BATCH_SIZE" "$PATHS" "$CHALLENGES" "$INVALIDATED" "$PASS_RATE" \
    "$DEPLOY_TIME" "$COMMIT_TIME" "$SETTLE_TIME" "$TOTAL_TIME" \
    "$DEPLOY_GAS" "$COMMIT_GAS" "$CHALLENGE_GAS" "$SETTLE_GAS" "$TOTAL_GAS" >> "$CSV"
done

cat "$CSV"
