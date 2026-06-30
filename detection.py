"""
detection.py — Detection signals for Provenance Guard.

Signal 1: Groq LLM classification (semantic).
Signal 2: Stylometric heuristics (structural).

Both return a score between 0.0 and 1.0, where 1.0 means the text looks
AI-generated and 0.0 means it looks human-written.
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

    match = re.search(r"[0-9]*\.?[0-9]+", raw)
    if not match:
        return 0.5  # fall back to "uncertain" if we can't parse a number

    score = float(match.group())
    return max(0.0, min(1.0, score))


def stylometric_signal(text):
    """
    Signal 2: structural heuristics computed in pure Python.

    Measures three properties that tend to differ between human and AI writing:
      1. Sentence-length variance  (AI = uniform/low variance)
      2. Vocabulary diversity      (type-token ratio; AI = lower diversity)
      3. Punctuation density       (AI = predictable/regular)

    Each property is converted to a 0.0-1.0 "AI-likeness" sub-score, and the
    three are averaged. Returns a float between 0.0 and 1.0, where 1.0 means
    the text looks structurally AI-like.
    """
    # Split into sentences on ., !, ?  (keep it simple — no libraries)
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"\b\w+\b", text.lower())

    # Guard against very short input that can't be measured meaningfully
    if len(sentences) < 2 or len(words) < 5:
        return 0.5  # not enough text to judge — return "uncertain"

    # -- 1. Sentence-length variance --------------------------------------
    # Human writing varies sentence length a lot; AI tends to be uniform.
    sentence_lengths = [len(re.findall(r"\b\w+\b", s)) for s in sentences]
    mean_len = sum(sentence_lengths) / len(sentence_lengths)
    variance = sum((x - mean_len) ** 2 for x in sentence_lengths) / len(sentence_lengths)
    std_dev = variance ** 0.5
    # Low std dev = uniform = AI-like. Normalize: std_dev of ~8+ words = very human.
    # We invert so that low variation -> high AI score.
    variance_score = max(0.0, 1.0 - (std_dev / 8.0))

    # -- 2. Vocabulary diversity (type-token ratio) -----------------------
    # unique words / total words. Lower diversity = more repetitive = AI-like.
    ttr = len(set(words)) / len(words)
    # A TTR around 0.7+ is diverse (human); 0.4 or below is repetitive (AI-like).
    # Map a high TTR -> low AI score, low TTR -> high AI score.
    diversity_score = max(0.0, min(1.0, (0.75 - ttr) / 0.35))

    # -- 3. Punctuation density -------------------------------------------
    # Humans use varied/irregular punctuation; very regular comma/period use
    # reads as AI-like. We measure punctuation marks per word and compare to
    # a "natural" band; text that is very clean and regular scores higher.
    punctuation_marks = len(re.findall(r"[,;:\-()\"']", text))
    punct_density = punctuation_marks / len(words)
    # Very low punctuation variety (clean, regular prose) reads more AI-like.
    # Natural human writing tends to have ~0.08-0.20 marks per word.
    if punct_density < 0.05:
        punctuation_score = 0.7   # very clean -> leans AI
    elif punct_density > 0.25:
        punctuation_score = 0.3   # very irregular -> leans human
    else:
        punctuation_score = 0.5   # normal range -> neutral

    # -- Combine the three sub-scores -------------------------------------
    final = (variance_score + diversity_score + punctuation_score) / 3
    return max(0.0, min(1.0, final))


# -- Independent test -------------------------------------------------------
# Run this file directly (python detection.py) to test BOTH signals on their
# own before relying on them in the app.
if __name__ == "__main__":
    ai_text = (
        "Artificial intelligence has revolutionized numerous industries by "
        "enabling unprecedented levels of efficiency and accuracy. Organizations "
        "across various sectors are leveraging these powerful tools to optimize "
        "their operations and drive innovation. The benefits are substantial and "
        "the applications are widespread across the modern economy."
    )

    human_text = (
        "ok so i finally watched that show everyone keeps talking about and "
        "honestly? kinda mid. like the first three episodes draaag and then it "
        "suddenly gets good around ep 5 which, who has the patience for that lol. "
        "anyway. worth it i guess if you can push through"
    )

    print("=== Groq signal (Signal 1) ===")
    print("AI-ish text:    ", groq_signal(ai_text))
    print("Human-ish text: ", groq_signal(human_text))
    print()
    print("=== Stylometric signal (Signal 2) ===")
    print("AI-ish text:    ", round(stylometric_signal(ai_text), 3))
    print("Human-ish text: ", round(stylometric_signal(human_text), 3))