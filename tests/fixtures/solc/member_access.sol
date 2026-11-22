contract Token {
    function transfer(address to, uint256 amount) external {}
    uint256 public supply;
}
contract Base {
    uint256 public seed;
    function baseFn() internal virtual {}
    function hidden() private {}
}
library SafeMath {
    function add(uint256 a, uint256 b) internal pure returns (uint256) {}
}
contract Vault is Base {
    using SafeMath for uint256;
    Token token;
    uint256[] values;
    uint256 total;
    function run() external {
        token.transfer(address(0), 1);
        uint256 s = token.supply();
        values.push(s);
        s = s + values.length;
        this.vaultFn();
        super.baseFn();
        s = this.seed();
        total.add(s);
    }
    function vaultFn() public {}
}
