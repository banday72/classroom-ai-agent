"""Orchestrates 'solve this assignment'.

WHAT: The single place that combines the AI client with the prompts to go
      from assignment info -> full solution text.
WHY:  main.py should not know about prompts or HTTP. It passes an info dict
      and receives text back.
HOW:  Build (system, user) messages and call AIClient().chat(). Any provider
      or prompt change stays inside the ai/ package.
"""

from .client import AIClient, AIError
from .prompts import SYSTEM_PROMPT, build_assignment_prompt, build_regeneration_prompt


def solve_assignment(assignment_info: dict) -> str:
    """Return the AI solution text for one assignment."""
    client = AIClient()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_assignment_prompt(assignment_info)},
    ]
    return client.chat(messages)


def regenerate_solution(assignment_info: dict) -> str:
    """A second attempt (used by the review menu)."""
    client = AIClient()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_regeneration_prompt(assignment_info)},
    ]
    return client.chat(messages)


__all__ = ["solve_assignment", "regenerate_solution", "AIError"]