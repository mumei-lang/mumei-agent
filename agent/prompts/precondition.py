"""Prompt template for precondition/postcondition and other non-effect violations."""
import json


def build_prompt(source_code: str, error_log: str, report_data: dict) -> str:
    """Build a prompt for fixing precondition/postcondition violations."""
    return f"""
You are an expert in the Mumei language. The following code failed formal verification.
Please fix the 'requires' (precondition) to resolve the mathematical contradiction.

# Source code:
{source_code}

# Error log:
{error_log}

# Verification report (counter-example data):
{json.dumps(report_data, indent=2)}

Output only the fixed code in ```mumei ... ``` format.
"""
