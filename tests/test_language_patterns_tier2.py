"""Unit tests for the Tier-2 advisory detectors added to
``agent/language_patterns.py`` — Solidity weak randomness / zero-address,
Rust escape hatches, Python dangerous calls and mutation-during-iteration,
and TypeScript ``x!``/``JSON.parse``/``eval``/``innerHTML``/for-of mutation.
"""

from __future__ import annotations

from agent.language_patterns import language_pattern_issues


def _issues(source: str, language: str):
    return language_pattern_issues(source, language)


# ---------------------------------------------------------------------------
# Solidity
# ---------------------------------------------------------------------------


def test_solidity_weak_randomness_blockhash_flags() -> None:
    source = """contract C {
    function pick() public returns (uint256) {
        return uint256(blockhash(block.number - 1)) % 10;
    }
}"""
    issues = _issues(source, "solidity")
    assert any("randomness" in i.message for i in issues)


def test_solidity_weak_randomness_keccak_timestamp_flags() -> None:
    source = """contract C {
    function pick() public returns (uint256) {
        return uint256(keccak256(abi.encodePacked(block.timestamp))) % 10;
    }
}"""
    issues = _issues(source, "solidity")
    assert any("randomness" in i.message for i in issues)


def test_solidity_weak_randomness_modulo_flags() -> None:
    source = """contract C {
    function pick() public returns (uint256) {
        return block.prevrandao % 10;
    }
}"""
    issues = _issues(source, "solidity")
    assert any("randomness" in i.message for i in issues)


def test_solidity_plain_timestamp_use_does_not_flag() -> None:
    source = """contract C {
    uint256 public deadline;
    function setDeadline() public {
        deadline = block.timestamp + 1 days;
    }
}"""
    issues = _issues(source, "solidity")
    assert not any("randomness" in i.message for i in issues)


def test_solidity_zero_address_missing_check_flags() -> None:
    source = """contract C {
    address public owner;
    function setOwner(address newOwner) public {
        owner = newOwner;
    }
}"""
    issues = _issues(source, "solidity")
    assert any("zero-address" in i.message for i in issues)


def test_solidity_zero_address_check_suppresses() -> None:
    source = """contract C {
    address public owner;
    function setOwner(address newOwner) public {
        require(newOwner != address(0));
        owner = newOwner;
    }
}"""
    issues = _issues(source, "solidity")
    assert not any("zero-address" in i.message for i in issues)


def test_solidity_zero_address_private_fn_skipped() -> None:
    source = """contract C {
    address public owner;
    function _set(address newOwner) internal {
        owner = newOwner;
    }
}"""
    issues = _issues(source, "solidity")
    assert not any("zero-address" in i.message for i in issues)


def test_solidity_zero_address_payable_param_flags() -> None:
    source = """contract C {
    address payable public sink;
    function setSink(address payable dest) external {
        sink = dest;
    }
}"""
    issues = _issues(source, "solidity")
    assert any("zero-address" in i.message and "`dest`" in i.message for i in issues)


def test_solidity_zero_address_non_stored_param_skipped() -> None:
    source = """contract C {
    address public owner;
    function isOwner(address who) public view returns (bool) {
        return who == owner;
    }
}"""
    issues = _issues(source, "solidity")
    assert not any("zero-address" in i.message for i in issues)


def test_solidity_unchecked_send_still_flags() -> None:
    source = """contract C {
    function payout(address payable dst) public {
        dst.send(1 ether);
    }
}"""
    issues = _issues(source, "solidity")
    assert any("`send`" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def test_rust_unsafe_block_flags() -> None:
    source = """fn raw(p: *const i32) -> i32 {
    unsafe { *p }
}"""
    issues = _issues(source, "rust")
    assert any("`unsafe`" in i.message for i in issues)


def test_rust_mem_forget_flags() -> None:
    source = """fn leak(x: Vec<u8>) {
    std::mem::forget(x);
}"""
    issues = _issues(source, "rust")
    assert any("mem::forget" in i.message for i in issues)


def test_rust_transmute_flags() -> None:
    source = """fn widen(x: u32) -> u64 {
    unsafe { std::mem::transmute(x) }
}"""
    issues = _issues(source, "rust")
    assert any("transmute" in i.message for i in issues)


def test_rust_clean_fn_skipped() -> None:
    source = "fn add(a: u64, b: u64) -> u64 {\n    a + b\n}\n"
    issues = _issues(source, "rust")
    assert not issues


# ---------------------------------------------------------------------------
# Python dangerous calls
# ---------------------------------------------------------------------------


def test_python_eval_flags() -> None:
    source = "def run(expr):\n    return eval(expr)\n"
    issues = _issues(source, "python")
    assert any("`eval`" in i.message for i in issues)


def test_python_exec_flags() -> None:
    source = "def run(code):\n    exec(code)\n"
    issues = _issues(source, "python")
    assert any("`exec`" in i.message for i in issues)


def test_python_pickle_loads_flags() -> None:
    source = "import pickle\n\ndef load(data):\n    return pickle.loads(data)\n"
    issues = _issues(source, "python")
    assert any("pickle.loads" in i.message for i in issues)


def test_python_os_system_flags() -> None:
    source = "import os\n\ndef purge(name):\n    os.system('rm ' + name)\n"
    issues = _issues(source, "python")
    assert any("os.system" in i.message for i in issues)


def test_python_subprocess_shell_true_flags() -> None:
    source = (
        "import subprocess\n\n"
        "def purge(name):\n"
        "    subprocess.run('rm ' + name, shell=True)\n"
    )
    issues = _issues(source, "python")
    assert any("subprocess.run" in i.message for i in issues)


def test_python_subprocess_shell_false_skipped() -> None:
    source = (
        "import subprocess\n\n"
        "def purge(name):\n"
        "    subprocess.run(['rm', name])\n"
    )
    issues = _issues(source, "python")
    assert not any("subprocess" in i.message for i in issues)


def test_python_yaml_load_no_loader_flags() -> None:
    source = "import yaml\n\ndef load(text):\n    return yaml.load(text)\n"
    issues = _issues(source, "python")
    assert any("yaml.load" in i.message for i in issues)


def test_python_yaml_load_safe_loader_skipped() -> None:
    source = (
        "import yaml\n\n"
        "def load(text):\n"
        "    return yaml.load(text, Loader=yaml.SafeLoader)\n"
    )
    issues = _issues(source, "python")
    assert not any("yaml" in i.message for i in issues)


def test_python_yaml_safe_load_skipped() -> None:
    source = "import yaml\n\ndef load(text):\n    return yaml.safe_load(text)\n"
    issues = _issues(source, "python")
    assert not any("yaml" in i.message for i in issues)


def test_python_dangerous_call_reports_enclosing_function() -> None:
    source = (
        "def outer():\n"
        "    def inner(x):\n"
        "        return eval(x)\n"
        "    return inner\n"
    )
    issues = _issues(source, "python")
    assert any("eval" in i.message and "`inner`" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Python mutation during iteration
# ---------------------------------------------------------------------------


def test_python_list_remove_during_iteration_flags() -> None:
    source = (
        "def prune(items):\n"
        "    for x in items:\n"
        "        if x < 0:\n"
        "            items.remove(x)\n"
    )
    issues = _issues(source, "python")
    assert any("mutates `items`" in i.message for i in issues)


def test_python_dict_assign_during_items_iteration_flags() -> None:
    source = (
        "def fix(mapping):\n"
        "    for k in mapping.items():\n"
        "        mapping[k] = 0\n"
    )
    issues = _issues(source, "python")
    assert any("mutates `mapping`" in i.message for i in issues)


def test_python_delete_key_during_iteration_flags() -> None:
    source = (
        "def drop(mapping):\n"
        "    for k in mapping:\n"
        "        del mapping[k]\n"
    )
    issues = _issues(source, "python")
    assert any("mutates `mapping`" in i.message for i in issues)


def test_python_mutating_other_collection_skipped() -> None:
    source = (
        "def copy(items, out):\n"
        "    for x in items:\n"
        "        out.append(x)\n"
    )
    issues = _issues(source, "python")
    assert not any("mutates" in i.message for i in issues)


def test_python_iterate_copy_skipped() -> None:
    source = (
        "def prune(items):\n"
        "    for x in list(items):\n"
        "        items.remove(x)\n"
    )
    issues = _issues(source, "python")
    assert not any("mutates" in i.message for i in issues)


# ---------------------------------------------------------------------------
# TypeScript
# ---------------------------------------------------------------------------


def test_typescript_non_null_assertion_flags() -> None:
    source = "function get(map: Map<string, number>): number {\n    return map.get('k')! + 1;\n}\n"
    issues = _issues(source, "typescript")
    assert any("non-null" in i.message for i in issues)


def test_typescript_inequality_not_flagged_as_assertion() -> None:
    source = "function check(a: number, b: number): boolean {\n    return a !== b && a != 0;\n}\n"
    issues = _issues(source, "typescript")
    assert not any("non-null" in i.message for i in issues)


def test_typescript_json_parse_unguarded_flags() -> None:
    source = "function load(text: string) {\n    return JSON.parse(text);\n}\n"
    issues = _issues(source, "typescript")
    assert any("JSON.parse" in i.message for i in issues)


def test_typescript_json_parse_in_try_skipped() -> None:
    source = (
        "function load(text: string) {\n"
        "    try {\n"
        "        return JSON.parse(text);\n"
        "    } catch {\n"
        "        return null;\n"
        "    }\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert not any("JSON.parse" in i.message for i in issues)


def test_typescript_eval_flags() -> None:
    source = "function run(code: string) {\n    return eval(code);\n}\n"
    issues = _issues(source, "typescript")
    assert any("`eval`" in i.message for i in issues)


def test_typescript_inner_html_flags() -> None:
    source = "function render(el: Element, html: string) {\n    el.innerHTML = html;\n}\n"
    issues = _issues(source, "typescript")
    assert any("innerHTML" in i.message for i in issues)


def test_typescript_for_of_push_flags() -> None:
    source = (
        "function dedup(arr: number[]) {\n"
        "    for (const x of arr) {\n"
        "        if (x > 0) {\n"
        "            arr.push(-x);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert any("mutates `arr`" in i.message for i in issues)


def test_typescript_for_of_push_other_array_skipped() -> None:
    source = (
        "function copy(arr: number[], out: number[]) {\n"
        "    for (const x of arr) {\n"
        "        out.push(x);\n"
        "    }\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert not any("mutates" in i.message for i in issues)


def test_javascript_aliases_to_typescript() -> None:
    issues = _issues(
        "function run(code) {\n    return eval(code);\n}\n", "javascript"
    )
    assert any("`eval`" in i.message for i in issues)
