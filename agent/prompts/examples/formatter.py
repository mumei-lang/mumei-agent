"""Helper to format few-shot examples for prompt injection."""


def format_examples(examples: list[dict], max_examples: int = 2) -> str:
    """Format a list of few-shot examples into a prompt section.

    Args:
        examples: List of {"before": str, "after": str, "explanation": str} dicts.
        max_examples: Maximum number of examples to include.

    Returns:
        Formatted string with example fixes, or empty string if no examples.
    """
    if not examples:
        return ""

    parts: list[str] = []
    for i, ex in enumerate(examples[:max_examples], 1):
        parts.append(
            f"# Example fix {i}:\n"
            f"## Before:\n```mumei\n{ex['before']}\n```\n"
            f"## After:\n```mumei\n{ex['after']}\n```\n"
            f"## Explanation:\n{ex['explanation']}"
        )
    return "\n\n".join(parts)
