# Solidity compiler snapshot fixtures

These envelopes capture operator-run solc standard-JSON output for the adjacent
source files. Regenerate with:

```sh
python3 tests/fixtures/solc/regenerate.py /path/to/solc-0.8.39
```

The output selection is `{"*":{"*":["metadata"],"":["ast"]}}`. The compiler
binary is the official linux-amd64 `solc-linux-amd64-v0.8.39+commit.ce47f2c8`
from binaries.soliditylang.org; verify its SHA-256 before use. The captured
binary has SHA-256
`b8b0642d46838575d3177628b685564b52f51f2aee546cb4dce781951d23c666`.
