"""Fix strategy: select prompt template based on violation type and call LLM."""
import re
from openai import OpenAI
from agent.prompts import effect_mismatch, effect_propagation, precondition


def get_fix(client: OpenAI, model: str, source_code: str, error_log: str, report_data: dict) -> str:
    """Generate a fix using the appropriate prompt template."""
    violation_type = report_data.get("violation_type", "")

    if violation_type == "effect_mismatch":
        prompt = effect_mismatch.build_prompt(source_code, error_log, report_data)
    elif violation_type == "effect_propagation":
        prompt = effect_propagation.build_prompt(source_code, error_log, report_data)
    else:
        prompt = precondition.build_prompt(source_code, error_log, report_data)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    content = response.choices[0].message.content or ""
    # Extract code block (handles various LLM fence labels)
    code_match = re.search(
        r'```(?:rust|rs|Rust|RS|mumei|mm|Mumei)?\s*\n(.*?)```',
        content,
        re.DOTALL,
    )
    if code_match:
        return code_match.group(1).strip()
    return content.strip()
