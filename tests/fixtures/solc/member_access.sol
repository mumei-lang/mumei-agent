contract Token {
    function transfer(address to, uint256 amount) external {}
    uint256 public supply;
}
contract Vault {
    Token token;
    uint256[] values;
    function run() external {
        token.transfer(address(0), 1);
        uint256 s = token.supply();
        values.push(s);
        s = s + values.length;
    }
}
