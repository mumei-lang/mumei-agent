contract Token {
    function transfer(address to, uint256 amount) external {}
    uint256 public supply;
}
contract Base {
    uint256 public seed;
    function baseFn() internal virtual {}
    function hidden() private {}
}
contract Vault is Base {
    Token token;
    uint256[] values;
    function run() external {
        token.transfer(address(0), 1);
        uint256 s = token.supply();
        values.push(s);
        s = s + values.length;
        this.vaultFn();
        super.baseFn();
        s = this.seed();
    }
    function vaultFn() public {}
}
