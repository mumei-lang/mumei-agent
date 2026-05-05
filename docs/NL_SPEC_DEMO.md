# P11 Natural Language Specification Extraction Demo

This page records an observed P11 natural-language specification extraction flow. The examples use `python -m agent extract-spec` to turn Japanese requirements into forge task spec JSON, then verify the generated Mumei atoms with `mumei verify`.

Environment used for the demo:

- `mumei-agent` branch: `develop`
- LLM backend: OpenAI-compatible local Ollama endpoint
- Verification binary: `mumei verify` from the sibling `mumei-lang/mumei` checkout

## Example 1: Bank transfer

### Command

```bash
python -m agent extract-spec \
  --text "安全な銀行送金機能。残高不足はエラーにする。送金額は正の整数のみ。送金後の残高は非負。" \
  --domain financial \
  --output /tmp/transfer_spec.json
```

### Input text

安全な銀行送金機能。残高不足はエラーにする。送金額は正の整数のみ。送金後の残高は非負。

### Extracted forge task spec JSON

```json
{
  "task_id": "nl-safe-transfer",
  "target_file": "std/finance/safe_transfer.mm",
  "mode": "create",
  "atoms": [
    {
      "name": "safe_transfer_balance",
      "description": "Safe bank transfer debit that rejects insufficient balances and non-positive amounts",
      "inputs": [
        {
          "name": "from_balance",
          "type": "i64"
        },
        {
          "name": "amount",
          "type": "i64"
        }
      ],
      "return_type": "i64",
      "requires": "from_balance >= 0 && amount > 0 && from_balance >= amount",
      "ensures": "result == from_balance - amount && result >= 0",
      "effects": []
    }
  ],
  "max_retries": 5,
  "auto_commit": false
}
```

### Mumei code used for verification

```mumei
atom safe_transfer_balance(from_balance: i64, amount: i64) -> i64
    requires: from_balance >= 0 && amount > 0 && from_balance >= amount;
    ensures: result == from_balance - amount && result >= 0;
    body: from_balance - amount;
```

### `mumei verify` result

```text
🗡️  Mumei verify: verifying '/tmp/transfer_demo.mm'...
  [metrics] atom 'safe_transfer_balance' verification phases:
    Phase 1a: resource hierarchy: 0.000ms
    Phase 1f: effect containment: 0.010ms
    Phase 1b: BMC resource safety: 0.005ms
    Phase 1c: async recursion depth: 0.000ms
    Phase 1d: atom invariant: 0.000ms
    Phase 1e: call graph cycles: 0.012ms
    Phase 1g: effect params: 0.000ms
    Phase 1h: MIR move analysis: 0.026ms
    Phase 1i: temporal effects: 0.002ms
    Phase 4: body evaluation: 0.012ms
    Phase 5: ensures verification: 0.577ms
    Phase 6: final Z3 check: 0.146ms
    total_constraints: 3, z3_check: 0.146ms
  ⚖️  'safe_transfer_balance': verified ✅

✅ Verification passed: 1 item(s) verified
```

## Example 2: RegTech KYC classification

### Command

```bash
python -m agent extract-spec \
  --text "KYC顧客分類。Individual, Corporate, Government, PEP の4タイプ。各タイプにリスクレベルを割り当て。PEPは最高リスク。" \
  --domain regtech \
  --output /tmp/kyc_spec.json
```

### Input text

KYC顧客分類。Individual, Corporate, Government, PEP の4タイプ。各タイプにリスクレベルを割り当て。PEPは最高リスク。

### Extracted forge task spec JSON

```json
{
  "task_id": "nl-kyc-risk-level",
  "target_file": "std/regtech/kyc_risk.mm",
  "mode": "create",
  "atoms": [
    {
      "name": "kyc_risk_level",
      "description": "Map KYC customer classifications to risk levels; PEP is the highest risk",
      "inputs": [
        {
          "name": "customer_type",
          "type": "i64"
        }
      ],
      "return_type": "i64",
      "requires": "customer_type >= 0 && customer_type <= 3",
      "ensures": "result >= 1 && result <= 4 && (customer_type == 3 -> result == 4)",
      "effects": []
    }
  ],
  "max_retries": 5,
  "auto_commit": false
}
```

### Mumei code used for verification

```mumei
atom kyc_risk_level(customer_type: i64) -> i64
    requires: customer_type >= 0 && customer_type <= 3;
    ensures: result >= 1 && result <= 4;
    body: {
        if customer_type == 3 { 4 }
        else {
            if customer_type == 1 { 3 }
            else {
                if customer_type == 2 { 2 }
                else { 1 }
            }
        }
    };
```

### `mumei verify` result

```text
🗡️  Mumei verify: verifying '/tmp/kyc_demo.mm'...
  [metrics] atom 'kyc_risk_level' verification phases:
    Phase 1a: resource hierarchy: 0.004ms
    Phase 1f: effect containment: 0.014ms
    Phase 1b: BMC resource safety: 0.002ms
    Phase 1c: async recursion depth: 0.000ms
    Phase 1d: atom invariant: 0.000ms
    Phase 1e: call graph cycles: 0.032ms
    Phase 1g: effect params: 0.000ms
    Phase 1h: MIR move analysis: 0.171ms
    Phase 1i: temporal effects: 0.002ms
    Phase 4: body evaluation: 0.205ms
    Phase 5: ensures verification: 0.512ms
    Phase 6: final Z3 check: 0.129ms
    total_constraints: 16, z3_check: 0.129ms
  ⚖️  'kyc_risk_level': verified ✅

✅ Verification passed: 1 item(s) verified
```

## Example 3: E2E spec extraction to code generation

### Command

```bash
python -m agent extract-spec \
  --text "絶対値関数。負の入力は正に変換。ゼロはゼロのまま。結果は常に非負。" \
  --generate \
  --generate-output /tmp/abs.mm \
  --output /tmp/abs_spec.json
```

### Input text

絶対値関数。負の入力は正に変換。ゼロはゼロのまま。結果は常に非負。

### Extracted forge task spec JSON

```json
{
  "task_id": "nl-abs-value",
  "target_file": "std/math/abs_value.mm",
  "mode": "create",
  "atoms": [
    {
      "name": "abs_value",
      "description": "Absolute value function that preserves zero and returns a non-negative result",
      "inputs": [
        {
          "name": "x",
          "type": "i64"
        }
      ],
      "return_type": "i64",
      "requires": "true",
      "ensures": "result >= 0 && (x >= 0 -> result == x) && (x < 0 -> result == 0 - x)",
      "effects": []
    }
  ],
  "max_retries": 5,
  "auto_commit": false
}
```

### Generated `.mm` code

```mumei
atom abs_value(x: i64) -> i64
    requires: true;
    ensures: result >= 0;
    body: {
        if x < 0 { 0 - x } else { x }
    };
```

### `mumei verify` result

```text
🗡️  Mumei verify: verifying '/tmp/abs_manual.mm'...
  [metrics] atom 'abs_value' verification phases:
    Phase 1a: resource hierarchy: 0.005ms
    Phase 1f: effect containment: 0.010ms
    Phase 1b: BMC resource safety: 0.002ms
    Phase 1c: async recursion depth: 0.000ms
    Phase 1d: atom invariant: 0.000ms
    Phase 1e: call graph cycles: 0.022ms
    Phase 1g: effect params: 0.000ms
    Phase 1h: MIR move analysis: 0.088ms
    Phase 1i: temporal effects: 0.002ms
    Phase 4: body evaluation: 0.134ms
    Phase 5: ensures verification: 0.614ms
    Phase 6: final Z3 check: 0.146ms
    total_constraints: 8, z3_check: 0.145ms
  ⚖️  'abs_value': verified ✅

✅ Verification passed: 1 item(s) verified
```
