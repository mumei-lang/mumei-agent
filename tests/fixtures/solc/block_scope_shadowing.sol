// SPDX-License-Identifier: MIT
pragma solidity 0.8.39;

contract Shadow {
    uint256 count;

    function track() external returns (uint256) {
        uint256 local = count + 1;
        {
            uint256 count = local;
            count = count + 10;
        }
        local = local + 1;
        return local + count;
    }
}
