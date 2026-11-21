// SPDX-License-Identifier: MIT
pragma solidity 0.8.39;

contract Guard {
    function check(uint256 value) internal pure returns (bool) {
        require(value > 0);
        return true;
    }
}
