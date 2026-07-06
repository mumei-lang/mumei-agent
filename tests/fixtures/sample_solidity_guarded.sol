// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract GuardedBank {
    mapping(address => uint256) public balances;
    bool private locked;

    modifier nonReentrant() {
        require(!locked, "reentrant");
        locked = true;
        _;
        locked = false;
    }

    function withdraw(uint256 amount) public nonReentrant {
        msg.sender.call{value: amount}("");
        balances[msg.sender] -= amount;
    }

    function manualWithdraw(uint256 amount) public {
        require(!locked, "reentrant");
        locked = true;
        msg.sender.call{value: amount}("");
        balances[msg.sender] -= amount;
        locked = false;
    }

    function getBalance() public view returns (uint256) {
        return balances[msg.sender];
    }
}
