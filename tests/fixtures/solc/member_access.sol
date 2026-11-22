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
struct Coin {
    uint256 v;
}
library Stamps {
    function stamp(Coin memory c) internal pure {}
}
using Stamps for Coin global;
contract Vault is Base {
    using SafeMath for uint256;
    Token public token;
    uint256[] values;
    uint256 total;
    Coin coin;
    Token[] tokens;
    function run() external {
        token.transfer(address(0), 1);
        uint256 s = token.supply();
        values.push(s);
        s = s + values.length;
        this.vaultFn();
        super.baseFn();
        s = this.seed();
        total.add(s);
        coin.stamp();
        tokens[0].transfer(address(0), 1);
        getToken().transfer(address(0), 1);
        new Token().transfer(address(0), 1);
        this.token().transfer(address(0), 1);
    }
    function vaultFn() public {}
    function getToken() internal returns (Token) {}
}
