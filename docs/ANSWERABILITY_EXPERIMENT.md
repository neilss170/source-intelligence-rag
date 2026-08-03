# Answerability experiment

The repository includes `backend/scripts/train_answerability.py` as a
reproducible experiment for distinguishing answerable document questions from
questions whose answers are absent.

The experiment used the Single Topic RAG Evaluation Dataset with a held-out
split by document ID. The split contained 96 training examples and 24 test
examples. This avoids placing questions from the same source document in both
sets.

## Results

| Configuration | Accuracy | Answer precision | Answer recall | F1 | False answers | False abstentions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense similarity and lexical features | 0.375 | 0.600 | 0.188 | 0.286 | 2 | 13 |
| Dense features plus cross-encoder scores | 0.417 | 1.000 | 0.125 | 0.222 | 0 | 14 |

The cross-encoder removed false answers on this small test split, but rejected
14 of 16 answerable questions. That tradeoff is not usable, so the learned
classifier is deliberately **not included in the production query path**.

The shipped system instead combines source routing, question intent, adaptive
retrieval, cross-encoder reranking, lexical evidence checks, and a strict
grounded-answer fallback. Generated model artifacts are ignored by Git.

## Next experiment

Use a larger, domain-diverse dataset with grouped cross-validation, calibrate
probabilities on a separate validation split, and report per-domain precision,
recall, and abstention rate before enabling a learned gate.
