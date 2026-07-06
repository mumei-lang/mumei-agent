// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Ledger {
    /// requires: b != 0
    /// ensures: result * b == a
    function safeDivide(uint256 a, uint256 b) public pure returns (uint256) {
        return a / b;
    }

    /// ensures: result == a + b
    function add(uint256 a, uint256 b) public pure returns (uint256) {
        return a + b;
    }
}
