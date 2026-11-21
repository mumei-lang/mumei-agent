// SPDX-License-Identifier: MIT
pragma solidity 0.8.39;

contract Overloaded {
    function choose(uint256 value) internal pure returns (uint256) {
        return value;
    }

    function choose(address value) internal pure returns (address) {
        return value;
    }

    function useChoice() internal pure returns (uint256) {
        return choose(1);
    }
}
