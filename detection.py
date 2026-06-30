"""
detection.py — Detection signals for Provenance Guard.

Signal 1: Groq LLM classification.
Sends text to llama-3.3-70b and asks it to judge whether the text reads
as human-written or AI-generated. Returns a score between 0.0 and 1.0,
where 1.0 means high confidence the text is AI-generated.
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

load_dotenv()  # reads GROQ_API_KEY from your .env file

_GROQ_MODEL = "llama-3.3-70b-versatile"


def _get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
    return Groq(api_key=api_key)


def groq_signal(text):
    """
    Signal 1: ask llama-3.3-70b whether the text is AI-generated.

    Returns a float between 0.0 and 1.0:
      1.0 = high confidence AI-generated
      0.0 = high confidence human-written
    """
    client = _get_groq_client()

    system_prompt = (
        "You are an expert at detecting AI-generated text. "
        "Assess whether the following text was written by a human or generated "
        "by an AI language model. Consider how natural, varied, and idiosyncratic "
        "the writing is. AI text often reads as coherent but generic, with uniform "
        "sentence structure. Human writing tends to be more varied and personal.\n\n"
        "Respond with ONLY a single number between 0.0 and 1.0, where 1.0 means you "
        "are highly confident the text is AI-generated and 0.0 means you are highly "
        "confident it is human-written. Respond with the number only — no words, "
        "no explanation."
    )

    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Pull the first number out of the response in case the model adds stray text
    match = re.search(r"[0-9]*\.?[0-9]+", raw)
    if not match:
        return 0.5  # fall back to "uncertain" if we can't parse a number

    score = float(match.group())
    return max(0.0, min(1.0, score))  # clamp into [0.0, 1.0]


# ── Independent test ──────────────────────────────────────────────────────
# Run this file directly (python detection.py) to test the signal on its own
# BEFORE wiring it into Flask. You should see the AI-ish text score high and
# the human-ish text score low.
if __name__ == "__main__":
    ai_text = (
        "Artificial intelligence has revolutionized numerous industries by "
        "enabling unprecedented levels of efficiency and accuracy. Organizations "
        "across various sectors are leveraging these powerful tools to optimize "
        "their operations and drive innovation."
    )

    human_text = (
        "ok so i finally watched that show everyone keeps talking about and "
        "honestly? kinda mid. like the first three episodes draaag and then it "
        "suddenly gets good around ep 5 which, who has the patience for that lol"
    )

    ambiguous_text = (
        "The meeting is scheduled for Thursday at 3pm. Please bring the quarterly "
        "reports and any updated figures from the finance team."
    )

    print("AI-ish text score:       ", groq_signal(ai_text))
    print("Human-ish text score:    ", groq_signal(human_text))
    print("Ambiguous text score:    ", groq_signal(ambiguous_text))
