# Retrieval and Generation Optimization Log

The frozen evaluation set contains 25 questions and has SHA-256
`04D55458CF35AE137E67516CD7B4D59ED3649E2BE448A1F23871AD48BF0D3253`.

Metrics marked `N/A` require the generation and judge stages and are not
estimated from retrieval-only runs.

| Iteration | Single change | Faithfulness | Answer relevancy | Context precision | Context recall | p95 latency |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | BM25 baseline, top-k 5, score floor 0.1 | N/A | N/A | 0.339 | 0.790 | 0.028 ms retrieval-only |
| 1 | Replace BM25 with BGE-small dense retrieval | N/A | N/A | 0.216 (-0.123) | 0.960 (+0.170) | 94.040 ms retrieval-only |
| 2 | Equal-weight BM25 + dense reciprocal-rank fusion | N/A | N/A | 0.200 (-0.016) | 0.920 (-0.040) | 80.092 ms retrieval-only |
| 3 | Reduce dense retrieval top-k from 5 to 3 | N/A | N/A | 0.320 (+0.104) | 0.860 (-0.100) | 38.846 ms retrieval-only |
| 4 | Enable metadata-aware section routing | N/A | N/A | 0.507 (+0.187) | 0.960 (+0.100) | 38.185 ms retrieval-only |
| 5 | Add exact-entity absence guard | N/A | N/A | 0.587 (+0.080) | 0.960 (+0.000) | 35.182 ms retrieval-only |
| 6 | Adaptive top-k: 1 lookup, 4 synthesis | N/A | N/A | 0.810 (+0.223) | 0.840 (-0.120) | 33.652 ms retrieval-only |

## Iteration 0 diagnosis

- “What degree is Neil pursuing?” returned nothing because exact keyword search
  did not connect “degree” with the stored Bachelor of Engineering wording.
- The supervised-learning question did not connect the category with Logistic
  Regression and K-Nearest Neighbors.
- Broad project-synthesis questions retrieved common “data” and “project” terms
  instead of the full set of relevant project evidence.
- Returning up to five lexical matches created substantial irrelevant context,
  making precision the main baseline bottleneck.

## Iteration 1 diagnosis

- Dense retrieval recovered semantic matches missed by BM25, including category
  questions about learning approaches and degree information.
- It returned five plausible but unsupported records for absent skills such as
  FastAPI and React, making negative-question precision zero.
- The unsupervised-learning query found the primary K-Means record but missed
  the related marketing-impact record.
- Broad data-science synthesis retrieved two of four labeled project records.
- The change is retained as a hybrid candidate because recall gained 0.170 while
  precision lost 0.123; it is not accepted as the final retriever.

## Iteration 2 diagnosis

- Equal-weight fusion elevated weak lexical matches such as education and
  summary records above project evidence.
- The supervised-learning question lost both relevant diabetes records.
- Negative skill questions still returned plausible semantic records.
- Both precision and recall fell relative to iteration 1, so this configuration
  is rejected. Dense retrieval from iteration 1 remains the active baseline.

## Iteration 3 diagnosis

- Removing two marginal results raised precision by 0.104 and nearly halved p95
  retrieval latency.
- Recall fell by 0.100, especially for multi-evidence synthesis questions.
- College and graduation questions ranked the summary and school entries above
  the degree entry, indicating that section routing is now more valuable than
  another global top-k adjustment.
- The precision gain is slightly larger than the recall loss, so top-k 3 is
  retained for the next experiment.

## Iteration 4 diagnosis

- Section routing removed cross-section noise and restored education retrieval.
- The internship question correctly searched the empty experience section.
- Explicit absent facts such as FastAPI and GPA still returned semantically
  similar records from the correct section.
- Multi-record synthesis remains incomplete at top-k 3.
- Both precision and recall improved, so section routing is retained.

## Iteration 5 diagnosis

- Absent FastAPI, React, GPA, and internship questions now return no context.
- The initial guard was too broad for an open algorithm question; narrowing it
  to explicit “Does/Has” lookups fixed the defect before recording the metric.
- Simple education questions still retrieve all education records at top-k 3.
- Synthesis questions need greater depth than direct factual questions.
- Precision improved without a recall loss, so the guard is retained.

## Iteration 6 diagnosis

- Direct lookups now return one focused record, raising precision above target.
- Synthesis questions retain up to four records, keeping aggregate recall above
  target.
- Top-1 dense ranking chose secondary-school records for two college/graduation
  questions; a reranker or exact date/title feature could correct these later.
- Broad data-science synthesis retrieved two of four labeled project records.
- Context precision (0.810) and context recall (0.840) both meet their success
  criteria, so this retrieval configuration is frozen for generation work.

## Winning retrieval configuration

- Model: `BAAI/bge-small-en-v1.5`
- Metadata-aware section routing
- Explicit absent-entity guard for yes/no lookups
- Adaptive retrieval depth: top-k 1 for direct lookup, top-k 4 for synthesis
- Minimum cosine similarity: 0.35

## Document evaluation set (mixed formats, model-written answers)

The resume set above measures the rule-based pipeline. Model-written answers
over arbitrary uploads are measured on a second set:
`document_eval_set.json`, 51 questions over a Markdown report, a TXT policy, a
DOCX handbook with a table and a 120-row CSV (`document_corpus.py` builds the
corpus; table answers are computed from the same rows). Run it with
`python scripts/evaluate_documents.py --name <run> [--generate] [--legacy]`.
Generation used `openai/gpt-oss-120b` on Groq.

| Run | Recall@k | Recall@1 | MRR | Passages | Fact accuracy | Cited support | Table accuracy | Abstention | Groundedness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Before: legacy chain, character chunker | 0.875 | 0.875 | 0.875 | 1.00 | 0.875 | 0.875 | 0.00 | 1.00 | 1.0 (hard-coded) |
| New chunker, legacy chain | 0.900 | 0.900 | 0.900 | 1.00 | - | - | - | - | - |
| After: hybrid + rerank, new chunker, SQL, guardrails | 1.000 | 0.950 | 0.975 | 3.15 | 1.000 | 0.975 | 1.00 | 1.00 | 0.949 |

Fact accuracy for "before" is after correcting the scorer for narrow no-break
spaces ("9 %"), which counted two right answers as wrong.

### What changed, and what each fixed

- **Adaptive top-k returned one passage for almost every question.** Model
  mode now keeps up to `RETRIEVAL_TOP_K` reranked passages (reranker
  probability >= 0.02, best 3 always kept). Fixed the comparison question
  (d25), which needs two passages.
- **Character slicing cut 16 of 24 report passages mid-sentence and left
  headings as passages of their own.** The chunker packs whole sentences with
  one sentence of overlap, never splits table rows, and carries the heading
  path into each passage title. DOCX is read in body order, so the benefits
  table sits under its heading instead of after the whole document (d37, d38).
- **Dense-only retrieval missed exact identifiers** ("SH-0042", d45). BM25 and
  dense candidates are fused by reciprocal rank and reranked by the cross
  encoder. Iteration 2 above rejected fusion for precision on the resume set;
  the reranker now carries precision, and the resume-tuned chain is kept
  unchanged for rule-based mode.
- **Totals and averages over 120 rows were impossible from retrieved rows**
  (0/5). CSV and XLSX uploads are loaded into a read-only in-memory SQLite
  database; the model asks for one SELECT and cites the result (5/5).
- **Groundedness was a constant.** Each cited sentence is now checked by
  `cross-encoder/nli-deberta-v3-xsmall` against one-to-three-sentence runs of
  the passages it cites, with and without the section path in front. Whole
  passages as premises scored true claims as neutral; the larger
  `nli-deberta-v3-base` was no more accurate and 2.3x slower. Claims that
  need arithmetic ("a reduction of five", d10, d25) remain flagged: NLI
  cannot check them. Table rows and SQL results are not NLI-checked.

### Latency and provider limits

Isolated questions take 1.6-1.8 s (about 0.5 s retrieval on CPU, the rest
the model call and the claim check); SQL questions take about 2.5 s for their
two model calls. Back-to-back evaluation medians are about 5 s because Groq's
free tier allows 8,000 tokens per minute. It also allows 200,000 tokens per
day, about 50-60 questions at this prompt size; when that is spent the
assistant says so instead of falling back silently to rule-based answers.

The final groundedness figure (0.949) re-scores the saved answers of the
last full run offline with the final claim checker, because the daily token
limit was reached before a further full run.
