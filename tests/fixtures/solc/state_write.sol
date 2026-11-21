// SPDX-License-Identifier: MIT
pragma solidity 0.8.39;

contract Counter {
    uint256 private count;

    function increment() internal {
        count = count + 1;
    }
}
