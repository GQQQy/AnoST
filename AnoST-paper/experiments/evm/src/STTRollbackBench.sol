// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract STTRollbackBench {
    struct Batch {
        bytes32 root;
        uint256 txCount;
        uint256 pathCount;
        uint256 invalidated;
        uint256 challengeCount;
        bool settled;
    }

    mapping(uint256 => Batch) public batches;
    mapping(uint256 => mapping(uint256 => bool)) public pathPruned;
    uint256 public nextBatchId;

    event BatchCommitted(uint256 indexed batchId, bytes32 root, uint256 txCount, uint256 pathCount);
    event PathChallenged(uint256 indexed batchId, uint256 indexed pathId, uint256 suffixLength, bytes32 newRoot);

    function commitBatch(bytes32 root, uint256 txCount, uint256 pathCount) external returns (uint256 batchId) {
        require(txCount > 0, "empty batch");
        require(pathCount > 0, "empty paths");
        batchId = nextBatchId++;
        batches[batchId] = Batch({
            root: root,
            txCount: txCount,
            pathCount: pathCount,
            invalidated: 0,
            challengeCount: 0,
            settled: false
        });
        emit BatchCommitted(batchId, root, txCount, pathCount);
    }

    function challengePath(
        uint256 batchId,
        uint256 pathId,
        uint256 suffixLength,
        bytes32[] calldata proof
    ) external returns (bytes32 newRoot) {
        Batch storage batch = batches[batchId];
        require(batch.txCount > 0, "unknown batch");
        require(!batch.settled, "settled");
        require(pathId < batch.pathCount, "bad path");
        require(!pathPruned[batchId][pathId], "already pruned");

        bytes32 h = keccak256(abi.encodePacked(batch.root, pathId, suffixLength));
        for (uint256 i = 0; i < proof.length; i++) {
            h = keccak256(abi.encodePacked(h, proof[i]));
        }

        pathPruned[batchId][pathId] = true;
        batch.invalidated += suffixLength;
        batch.challengeCount += 1;
        batch.root = h;

        emit PathChallenged(batchId, pathId, suffixLength, h);
        return h;
    }

    function settle(uint256 batchId) external returns (uint256 accepted) {
        Batch storage batch = batches[batchId];
        require(batch.txCount > 0, "unknown batch");
        require(!batch.settled, "settled");
        batch.settled = true;
        accepted = batch.txCount > batch.invalidated ? batch.txCount - batch.invalidated : 0;
    }
}
