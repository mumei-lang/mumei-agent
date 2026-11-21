// SPDX-License-Identifier: MIT
pragma solidity 0.8.39;

contract Base {
    function hook() internal virtual {}
}

contract Child is Base {
    function hook() internal override {}

    function invoke() internal {
        hook();
    }
}
