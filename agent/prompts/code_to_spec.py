"""Prompts for extracting natural language specifications from source code."""

CODE_TO_SPEC_SYSTEM_PROMPT = (
    "You are a specification engineer for the Mumei proof-driven language. "
    "Your task is to extract natural language specifications from existing code.\n\n"
    "Analyze the provided code and extract:\n"
    "- What the function does (purpose)\n"
    "- Preconditions (what must be true before execution)\n"
    "- Postconditions (what is guaranteed after execution)\n"
    "- Side effects (IO, state mutations, etc.)\n"
    "- Safety properties (overflow prevention, null checks, etc.)\n\n"
    "Output a natural language description that can be used as input to "
    "Mumei's specification extraction pipeline. "
    "Focus on the intent and behavior, not the syntax."
)


def build_code_to_spec_prompt(code: str, language: str) -> str:
    """Build a prompt for extracting a natural language spec from code."""
    return f"""# Code to analyze
Language: {language}
```{language}
{code}
```

# Task
Extract a natural language specification from this code.
Describe:
1. What this function does
2. Preconditions (what must be true before execution)
3. Postconditions (what is guaranteed after execution)
4. Side effects
5. Safety properties

Output ONLY the natural language specification, no code."""
