// SPDX-License-Identifier: MIT
pragma solidity 0.8.39;

contract Broken {
    function read() internal pure returns (uint256) {
        return missing;
    }
}
