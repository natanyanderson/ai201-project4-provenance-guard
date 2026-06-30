# Provenance Guard

A backend system that classifies submitted text as human-written or AI-generated, returns a calibrated confidence score, surfaces a plain-language transparency label, and lets creators appeal classifications they believe are wrong. Built as a Flask API that any creative-sharing platform could plug into.

## What It Does

When a creator submits text, Provenance Guard runs it through two independent detection signals, combines them into a single confidence score, maps that score to one of three transparency labels, and records the full decision in a structured audit log. Creators who believe they were misclassified can appeal, which flags the content for human review.

## Architecture

When a creator submits text, the submission endpoint receives it, runs it through both detection signals, combines the scores into a confidence score, maps that score to a transparency label, writes the full decision to the audit log, and returns the result. Appeals flow separately: the appeal endpoint logs the creator's reasoning alongside the original decision and flips the content's status to "under review" for a human to look at later.

```
SUBMISSION FLOW
===============
Creator
  |
  | (text)
  v
POST /submit
  |
  |--- Signal 1: Groq LLM --------> score (0.0-1.0)
  |--- Signal 2: Stylometric ------> score (0.0-1.0)
  |
  v
Confidence Scoring: (groq_score + stylometric_score) / 2
  |
  v
Transparency Label (map score -> label text)
  |
  v
Audit Log (write decision record)
  |
  v
Response -> Creator (result + score + label)


APPEAL FLOW
===========
Creator
  |
  | (content ID + reasoning)
  v
POST /appeal
  |
  v
Log appeal alongside original decision
  |
  v
Update status -> "under review"
  |
  v
Response -> Creator (confirmation)
```

## API Endpoints

| Endpoint | Method | Accepts | Returns |
|----------|--------|---------|---------|
| `/submit` | POST | `text`, `creator_id` | `content_id`, attribution, confidence, both signal scores, transparency label |
| `/appeal` | POST | `content_id`, `creator_reasoning` | confirmation + status `under_review` |
| `/log` | GET | (optional filters) | structured audit log entries as JSON |

## Detection Signals

The pipeline uses two genuinely independent signals — one semantic, one structural. They measure different properties of the text, which makes the combination more informative than either alone.

### Signal 1 — Groq LLM Classification (semantic)
The text is sent to `llama-3.3-70b-versatile`, which judges whether it reads as human-written or AI-generated and returns a score between 0.0 and 1.0. This captures semantic and stylistic coherence holistically — how natural and idiosyncratic the writing feels.

**Why this signal:** A large pretrained model already understands language and can pick up on the generic, over-coherent quality that AI text often has, without needing any training data.

**Blind spot:** AI text written with intentional slang, typos, or informal phrasing can fool the LLM into reading it as human. In the other direction, a very polished human writer can be flagged as AI because their writing is too clean.

### Signal 2 — Stylometric Heuristics (structural)
Pure-Python code (no external libraries) measures three statistical properties and averages them into a 0.0–1.0 score: sentence-length variance, vocabulary diversity (type-token ratio), and punctuation density. AI text tends to be structurally uniform; human writing is more variable.

**Why this signal:** It captures something the LLM doesn't — the measurable structural regularity of the text. It's also fully transparent and deterministic, which makes its decisions explainable.

**Blind spot:** A human who writes formally and consistently — an academic or technical writer — looks structurally uniform and can be misclassified as AI. An AI prompted to vary its sentence lengths would slip past it.

## Confidence Scoring

The two signal scores are averaged into a single confidence score:

```
confidence = (groq_score + stylometric_score) / 2
```

Both signals are weighted equally because they measure independent properties, and neither is reliably better than the other by default. The combined score is mapped to an attribution and label using asymmetric thresholds:

| Score Range | Attribution | Label Tier |
|-------------|-------------|------------|
| ≥ 0.75 | likely_ai | High-confidence AI |
| 0.41 – 0.74 | uncertain | Uncertain |
| ≤ 0.40 | likely_human | High-confidence human |

The uncertain band is deliberately wide. On a creative platform a false positive (calling a human's work AI) is worse than a false negative, so the system stays cautious and only commits to "AI" when both signals agree strongly. A useful side effect: because averaging pulls disagreeing signals toward the middle, the system naturally lands on "uncertain" when its two signals conflict — which is exactly when it *should* be unsure.

### Example Submissions (real scores)

**High-confidence case** — uniform, repetitive text:
> "The system processes data efficiently. The system analyzes data accurately. The system delivers results quickly..."
- Groq score: 0.90, Stylometric score: 0.68
- **Combined confidence: 0.79 → likely_ai (High-confidence AI label)**

**Low-confidence case** — casual, irregular text:
> "ok so i finally watched that show everyone keeps talking about and honestly? kinda mid. like the first three episodes draaag..."
- Groq score: 0.20, Stylometric score: 0.23
- **Combined confidence: 0.22 → likely_human (High-confidence human label)**

The two inputs produce very different scores (0.79 vs 0.22), confirming the scoring produces meaningful variation rather than a constant.

## Transparency Labels

The label text changes based on the confidence score — all three variants are reachable.

**High-confidence AI (score ≥ 0.75):**
> This content shows strong indicators of AI generation. Our system detected patterns consistent with AI-generated text, including uniform sentence structure and low stylistic variation. If you believe this is an error, you can submit an appeal.

**Uncertain (score 0.41 – 0.74):**
> Our system could not confidently determine the origin of this content. This does not mean something is wrong with your writing — it means the signals were mixed and the system is not sure either way. You may submit an appeal if you'd like a human to review it.

**High-confidence human (score ≤ 0.40):**
> This content shows strong indicators of human authorship. Our system detected variable sentence structure, diverse vocabulary, and natural stylistic patterns consistent with human writing. If you believe this is an error, you can submit an appeal.

The uncertain label is written to reassure rather than accuse — a formal academic writer who lands in the AI or uncertain range shouldn't feel penalized, so the label explicitly says the result doesn't mean something is wrong with their writing.

## Appeals Workflow

Any creator whose content has been classified can appeal by sending the `content_id` and their `creator_reasoning` to `POST /appeal`. The system:
1. Finds the original decision in the audit log
2. Updates its status to `under_review`
3. Attaches the creator's reasoning and an appeal timestamp
4. Returns confirmation

Automated re-classification is intentionally not performed — an appeal flags the content for a human reviewer, who sees the original text, both signal scores, the confidence score, the assigned label, and the creator's reasoning all in one log entry.

## Rate Limiting

The `/submit` endpoint is limited to **10 requests per minute per IP** using Flask-Limiter. The reasoning: a legitimate creator submitting their own work would rarely need more than a few submissions per minute, so 10 comfortably covers real use while blocking a script trying to flood the system. The limit is per-IP because that's the natural unit of abuse for an unauthenticated endpoint.

**Verification** — sending 12 rapid requests returns 200 until the limit is hit, then 429:
```
200
200
200
200
200
200
429
429
429
429
429
429
```

## Audit Log

Every submission writes a structured JSON entry; appeals update the matching entry. A sample log showing both a normal classification and an appealed entry:

```json
[
  {
    "content_id": "7d0b79b7-eff6-49ae-b4f0-18ebe9489994",
    "creator_id": "test-user-1",
    "timestamp": "2026-06-30T00:53:04.296432+00:00",
    "attribution": "likely_ai",
    "confidence": 0.8,
    "llm_score": 0.8,
    "status": "under_review",
    "appeal_reasoning": "I wrote this myself from personal experience.",
    "appeal_timestamp": "2026-06-30T01:12:34.734287+00:00"
  },
  {
    "content_id": "4ab980b4-4226-4609-b045-05559ea01038",
    "creator_id": "test-human",
    "timestamp": "2026-06-30T01:04:10.926389+00:00",
    "attribution": "likely_human",
    "confidence": 0.22,
    "llm_score": 0.2,
    "stylometric_score": 0.23,
    "status": "classified",
    "appeal_reasoning": null
  }
]
```

Each entry captures the timestamp, content ID, attribution, combined confidence, both individual signal scores, the status, and whether an appeal has been filed.

## Known Limitations

**Formal human writing is the system's most likely false positive.** A human academic or technical writer produces highly uniform, low-variance, typo-free text. The stylometric signal reads that uniformity as AI-like, and the Groq signal may flag it as suspiciously polished. Both signals push in the same wrong direction, so the system can land a genuinely human writer in the uncertain or AI range. This is a direct consequence of *what the signals measure* — structural regularity and polish are exactly the properties that overlap between formal humans and AI. The wide uncertain band and the appeals workflow are the mitigations, not a fix.

**Intentionally degraded AI text is the hardest case to catch.** AI output deliberately seeded with slang, typos, and varied sentence lengths defeats both signals at once: it no longer reads as generic to the LLM, and it no longer looks uniform to the heuristics. The system has no counter-signal for this, so such text can score as human. Detecting deliberately disguised AI text is an open problem, and this system does not solve it.

## Spec Reflection

**One way the spec helped:** Writing `planning.md` first — especially the confidence thresholds and the three label variants — meant the implementation was just translating decisions I'd already made. When it came time to build the scoring logic and labels, the thresholds (≥0.75, ≤0.40) and the exact label text were already written down, so there was no guesswork during coding.

**One way the implementation diverged:** My spec implied that "clearly AI" text would reliably score in the high-confidence AI range. In practice, polished-but-short AI paragraphs often scored only in the uncertain band, because the stylometric signal is more conservative than the LLM and averaging pulled the combined score down. Rather than re-weighting the signals to force a higher score, I kept the equal weighting and treated this as correct behavior — the system being cautious when its two signals disagree is the safer design for a creative platform.

## AI Usage

**Instance 1 — Generating the Flask skeleton and signal functions from my spec.** I gave an AI tool my detection-signals section and architecture diagram from `planning.md` and asked it to generate the Flask app skeleton, the Groq signal function, and the stylometric signal function. I tested each signal independently before wiring it into the endpoint — running them on known AI and human text to confirm the scores separated correctly — and verified the scoring logic matched my own thresholds (≥0.75 / ≤0.40) rather than accepting whatever ranges were generated.

**Instance 2 — Building the confidence scoring and label logic.** I asked the AI to generate the score-combination logic and the label-generation function from my uncertainty-representation and transparency-label sections. I checked the generated label function against my spec to confirm all three variants were reachable and that the text matched what I had written, then tested by submitting inputs that scored in each range to confirm the high-confidence AI, uncertain, and human labels all triggered.