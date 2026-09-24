"""All prompts the AI sees, in one place so they are easy to tune.

WHAT: SYSTEM_PROMPT is the standing set of rules for HOW the model behaves.
      build_assignment_prompt(info) packs the assignment data into a clearly
      labelled "user" message.
WHY:  A good prompt is what turns a generic chatbot into a reliable study
      assistant: it fixes the output format, forbids hallucinations and
      forces the "show your reasoning, then the final answer" style.
HOW:  The assignment arrives as a dict:
        {"course": ..., "assignment_title": ..., "description": ...,
         "due_date": ..., "materials": "<extracted text from files>"}
      We present each field with labels so the model can tell them apart,
      and we print a short JSON preview in the intro-block so it can
      distinguish fact from structure.
"""

import json

SYSTEM_PROMPT = """You are a careful, honest study assistant for an Artificial Intelligence student.
Your job is to read one assignment and produce a complete, well-organised answer that the student can review and submit.

Follow these rules strictly:
1. UNDERSTAND first. Restate what the assignment is asking in your own words before answering.
2. Identify the required tasks. If the assignment has several parts, list them and answer each one.
3. Solve step by step. Do not skip steps, even for "obvious" results.
4. Separate reasoning from the final answer. Use a section marked `## Reasoning` (the working, formulas, logic) followed by a section marked `## Final Answer` (the exact result the student would hand in).
5. Follow the requested format. If the assignment demands a specific layout, document type, or template, obey it.
6. NEVER invent information. If you do not know something, or the assignment references a file, formula, or reading the student did not provide, say so clearly under a `## Missing information` heading instead of guessing.
7. If the description is empty and no material text is provided, say that you received no content and ask for it.
8. Use Markdown headings (## and ###), bullet lists, and numbered steps. Keep the whole answer readable and professional.
9. End with a short `## Summary` of what you did.

Never claim you submitted anything, never invent due dates, and never write code unless the assignment asks for code."""


def build_assignment_prompt(info: dict) -> str:
    """Turn the assignment info dict into the user message for the AI."""
    preview = json.dumps(info, indent=2, ensure_ascii=False)
    return f"""Analyse and solve the following assignment. The facts are given exactly, do not invent details.

{preview}

Begin your answer now."""


def build_regeneration_prompt(info: dict) -> str:
    """Prompt used when the user asks for a fresh attempt."""
    return build_assignment_prompt(info) + "\n\nThis is a second attempt: please try a different approach or cleaner structure."