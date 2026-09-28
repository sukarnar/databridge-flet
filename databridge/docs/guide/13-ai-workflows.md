---
title: AI workflows
icon: ACCOUNT_TREE
permission: use_ai
pages: [workflow]
keywords: workflow, node, canvas, llm node, router, transform, sql, output, test, estimate, publish, batch, per row, classify, summarize
---
# AI workflows

A workflow sends your data through LLMs step by step, for example: *read tickets → classify each one → route urgent ones → save the results as a new source*.

## Build one

1. Go to **AI > Workflows** and click **New workflow**. Start from a template: *Classify each row*, *Summarize a dataset*, *Answer a question*, or *Blank*.
2. **Add nodes** from the left panel. **Connect** them: click the dot on a node's right edge, then click the node it should feed. Drag nodes to move them.
3. Click a node to **configure** it on the right.

| Node | Does |
|---|---|
| Dataset rows | Rows from a source or a published mapping (columns, filter, row limit) |
| Run input | One row from the run form or the API call |
| Transform | Add columns with formulas, or filter rows |
| SQL (aggregate) | A read-only query over the incoming rows (table `rows`), e.g. totals per region |
| LLM | Prompts a model per row, or per batch of rows; output as text or as JSON fields |
| Router | Splits rows by a condition such as `[urgency] >= 4` (yes / no) |
| Output dataset | Saves the rows as a source you can map and serve |

## LLM node tips

- **Data in the prompt:** `{{ data }}` inserts the row (or the batch as a table) inside safe delimiters. Use `{{ row.Column }}` for one value and `{{ input.name }}` for run input.
- **JSON fields:** choose **JSON fields** output and list the fields (e.g. `category` as an enum, `urgency` as an integer). Each field becomes a column, and replies are checked and retried if invalid.
- **Save tokens:** send only the columns the model needs (**Columns sent**), and aggregate with a SQL node before summarizing big tables.

## Before a real run

1. **Check & estimate:** a dry run. It shows calls, expected tokens, which columns are sent or masked, and what guardrails found. No model is called.
2. **Test (3 rows):** runs on 3 rows. The run shows the exact prompts sent and the replies.
3. **Run:** processes everything. Large runs ask you to confirm the estimated tokens.

Each run opens a summary with a table per node, the output, and a **review** table of flagged and rejected rows with reasons.

## Publish and call from other systems

**Publish** freezes the current version. Other systems call it with an API key allowed for that workflow:

```
curl -X POST -H "X-API-Key: <key>" -H "Content-Type: application/json" \
     -d '{"input": {"question": "..."}}' {{api_base}}/api/v1/workflows/<slug>/run
```

Guardrails are explained in [AI guardrails](guide:ai-guardrails).
