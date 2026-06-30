# Provenance Guard — Planning Document

## Overview
Provenance Guard is a backend API that classifies submitted text content as human-written or AI-generated, returns a confidence score, surfaces a plain-language transparency label, and provides an appeals workflow for contested classifications.

## Detection Signals

### Signal 1: Groq LLM Classification
**What it measures:** Whether the text reads as human-written or AI-generated, assessed holistically by llama-3.3-70b. Captures semantic coherence, stylistic patterns, and how naturally the writing flows.
**Output:** A probability score between 0.0 and 1.0, where 1.0 means high confidence the text is AI-generated.
**Why it differs between human and AI:** AI-generated text tends to be coherent and consistent in tone in ways that feel generic. Human writing has more idiosyncratic phrasing, tangents, and voice.
**Blind spot:** AI text written with intentional slang, typos, or informal language may fool the LLM into reading as human. A very polished human writer may get flagged as AI because their writing is too clean and coherent.

### Signal 2: Stylometric Heuristics
**What it measures:** Statistical structural properties of the text — sentence-length variance, type-token ratio (vocabulary diversity), and punctuation density. Computed in pure Python with no external libraries.
**Output:** A score between 0.0 and 1.0, where 1.0 means the text looks structurally AI-like (uniform, low variance).
**Why it differs between human and AI:** AI text tends to be structurally uniform — sentences cluster around similar lengths, vocabulary is consistent, punctuation is predictable. Human writing is more variable.
**Blind spot:** A human who writes formally and consistently — like an academic or technical writer — will look structurally uniform and may be misclassified as AI. An AI prompted to vary its sentence lengths would evade this signal.

### Combining Signals
The two signal scores are averaged into a single confidence score between 0.0 and 1.0:

```
confidence = (groq_score + stylometric_score) / 2
```

Both signals are weighted equally because they measure genuinely independent properties — one semantic, one structural. Neither is more reliable than the other by default.

## Uncertainty Representation

The confidence score maps to three label tiers:

| Score Range | Label Tier |
|-------------|------------|
| ≥ 0.75 | High-confidence AI |
| 0.41 – 0.74 | Uncertain |
| ≤ 0.40 | High-confidence human |

A score of 0.51 produces an uncertain label, not a high-confidence one. A score of 0.95 produces a high-confidence AI label. The thresholds are intentionally asymmetric — the uncertain band is wide because false positives (labeling a human as AI) are worse than false negatives on a creative writing platform.

## Transparency Labels

### High-Confidence AI (score ≥ 0.75)
> ⚠️ This content shows strong indicators of AI generation.
> Our system detected patterns consistent with AI-generated text,
> including uniform sentence structure and low stylistic variation.
> If you believe this is an error, you can submit an appeal below.

### Uncertain (score 0.41 – 0.74)
> 🔍 Our system could not confidently determine the origin of this content.
> This does not mean something is wrong with your writing — it means
> the signals were mixed and the system is not sure either way.
> You may submit an appeal if you'd like a human to review it.

### High-Confidence Human (score ≤ 0.40)
> ✅ This content shows strong indicators of human authorship.
> Our system detected variable sentence structure, diverse vocabulary,
> and natural stylistic patterns consistent with human writing.
> If you believe this is an error, you can submit an appeal below.

## Appeals Workflow

**Who can appeal:** Any creator whose content has been classified.
**What they provide:** The content ID and their reasoning for why the classification is wrong.
**What the system does:**
1. Logs the appeal alongside the original decision in the audit log
2. Updates the content status to "under review"
3. Returns confirmation that the appeal was received

**What a human reviewer sees:** The original content, the two signal scores, the confidence score, the label assigned, and the creator's appeal reasoning — all in one audit log entry.

## Anticipated Edge Cases

**Edge case 1 — Formal academic writer:** A human whose writing is highly structured, consistent sentence lengths, and no typos. The stylometric heuristic scores them as AI-like, and Groq may also flag them as suspiciously polished. Result: a false positive (high-confidence AI label on human work). The wide uncertain band and appeals workflow are the primary mitigations.

**Edge case 2 — AI text with intentional errors:** An AI-generated piece that includes deliberate slang, typos, and informal language to mimic human writing. Both signals may miss it, producing an uncertain or high-confidence human label on AI-generated content. This is the harder failure mode — the system has no reliable counter-signal for intentionally degraded AI text.

## API Surface

### POST /submit
**Accepts:** Text content (string)
**Returns:** Attribution result, confidence score (0.0–1.0), transparency label text

### POST /appeal
**Accepts:** Content ID, creator's reasoning (string)
**Returns:** Confirmation that appeal was received and status updated to "under review"

### GET /log
**Accepts:** Optional filters (date, attribution result, status)
**Returns:** Structured audit log entries with content, signal scores, confidence score, label, and any associated appeal

## Rate Limiting
The POST /submit endpoint is rate limited to prevent flooding. Limit: 10 requests per minute per IP address. Reasoning: a legitimate creator submitting work would rarely need more than a few submissions per minute; 10 allows reasonable use while blocking automated abuse.

## Architecture

When a creator submits text, it flows through the system as follows: the submission endpoint receives the text, runs it through both detection signals, combines the scores into a confidence score, maps that score to a transparency label, writes the full decision to the audit log, and returns the result to the creator. Appeals flow separately: the appeal endpoint receives the creator's reasoning, logs it alongside the original decision, and flips the content status to "under review" for human review.

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

## AI Tool Plan

### M3 — Submission Endpoint + First Signal (Groq)
**Spec sections provided to AI:** Detection Signals (Signal 1) + Architecture diagram
**What I'll ask for:** Flask app skeleton with POST /submit endpoint + the Groq LLM signal function that takes text and returns a score between 0.0 and 1.0
**How I'll verify:** Test the Groq signal function directly with 3 inputs (clearly AI text, clearly human text, ambiguous text) and confirm the scores differ meaningfully before wiring into the endpoint

### M4 — Second Signal + Confidence Scoring
**Spec sections provided to AI:** Detection Signals (Signal 2) + Uncertainty Representation + Architecture diagram
**What I'll ask for:** Stylometric heuristic function that returns a score between 0.0 and 1.0 + confidence scoring logic that averages the two signals
**How I'll verify:** Run clearly AI text and clearly human text through both signals and confirm the combined confidence scores differ meaningfully and map to different label tiers

### M5 — Production Layer
**Spec sections provided to AI:** Transparency Labels + Appeals Workflow + Architecture diagram
**What I'll ask for:** Label generation logic that maps confidence score to label text + POST /appeal endpoint + GET /log endpoint + rate limiting on POST /submit
**How I'll verify:** Test that all three label variants are reachable by submitting text that scores in each range, and confirm that a POST /appeal correctly updates status and appears in GET /log