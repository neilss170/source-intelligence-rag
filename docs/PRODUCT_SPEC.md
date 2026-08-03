# Product specification

## Goal

Provide one minimal chatbot for three tasks:

1. Ask uploaded files and receive evidence-backed answers.
2. Ask normal conversational questions using recent chat context.
3. Ask for current products, prices, news, or links using compact web search.

## Answer contract

- Start with the direct answer.
- Match length and structure to the question's intent.
- Never treat retrieval alone as proof.
- Cite document evidence only when it supports the claim.
- Say that data is unavailable when the documents do not contain it.
- Do not invent URLs, product models, prices, dates, or metrics.
- Mark live information as time-sensitive and show its sources.

## Supported inputs

| Format | Treatment |
| --- | --- |
| PDF | page-level text extraction; scanned PDFs require OCR |
| DOCX | paragraphs and tables |
| TXT/Markdown | paragraph-aware text chunks |
| CSV | header-aware records with row provenance |
| JSON | one evidence record per top-level item |
| XLSX | header-aware worksheet rows |

## Success criteria

- No unrelated document dumps.
- No affirmative yes/no answer without subject evidence.
- Follow-ups such as “name a few” inherit the prior topic.
- Unsupported document questions have no misleading citations.
- Live-search answers use no more than three short sources by default.
- New uploads and deletions immediately refresh retrieval.
- Tests and frontend build pass in continuous integration.
