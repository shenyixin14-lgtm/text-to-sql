# Natural Language to SQL (Text-to-SQL)

A system that turns plain-English questions into executable SQL queries and returns the answer. Ask *"Which customer has spent the most?"* and get the result — no SQL required.

Built with Python and an LLM, with a focus on the parts that make a Text-to-SQL system reliable rather than just a demo: output handling, self-correction, safety, and quantitative evaluation.

## What it does

```
Question ("Which city has the highest average score?")
   -> LLM generates SQL, given the database schema
   -> Output is cleaned and safety-checked
   -> SQL is executed against the database
   -> Result returned; on failure, the error is fed back and the query is regenerated
```

## Features

- **Schema-aware SQL generation** — the model is given the table structures and produces queries across single and multiple tables (aggregation, grouping, `JOIN`).
- **Output sanitisation** — strips markdown fences and reasoning-model `<think>` tags so raw model output can't break execution.
- **Self-correction** — when a query fails, the error message is fed back to the model, which analyses it and retries (bounded number of attempts).
- **Safety validation** — a read-only whitelist: only `SELECT` queries run; `DROP`, `DELETE`, `UPDATE` and other destructive statements are blocked before execution.
- **Evaluation suite** — measures *execution accuracy* (comparing query results, not query text) over a labelled test set.

## Getting started

Requirements: Python 3.9+ and a free [Groq](https://console.groq.com) API key.

```bash
pip install groq python-dotenv pandas
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

Run:

```bash
python text_to_sql.py
```

## Usage

```python
ask("Which customer has spent the most?")
# Attempt 1, generated SQL: SELECT customers.name, SUM(orders.amount) AS total ...
# Executed successfully
#      name  total
# 0     Bob   8200
```

## Evaluation

The system is evaluated on a labelled test set covering counting, filtering, aggregation, grouping, ordering and multi-table joins.

Accuracy is measured as **execution accuracy**: a generated query is correct if its *result* matches the reference query's result, rather than requiring identical SQL text — since a question usually has many valid SQL formulations.

| Stage | Accuracy |
|-------|----------|
| Initial comparison (single table) | 87.5% |
| After refining result comparison | 100% |
| Extended to multi-table joins | 80% (automatic) |
| After manual review of flagged cases | 100% |

## Notes on evaluation design

Building the evaluation was as instructive as building the system itself.

Strict result comparison produced **false negatives** — cases where the generated query was correct but was marked wrong. Two examples:

- The model aliased a column (`COUNT(*) AS student_count`), so the result was identical but the column name differed.
- For a join, the model produced a `LEFT JOIN` with `COALESCE` — arguably *more* robust than the reference answer — but returned an extra column, so automatic comparison failed.

The comparison logic was refined to ignore column names, column order and row order, which removed most false negatives. The remaining cases show a real limit: fully automatic comparison of SQL results is an open problem, because a single reference answer can't capture every valid output shape. The final approach combines automatic evaluation with manual review of flagged cases — treating the accuracy figure as something to be understood, not just reported.

## Tech stack

Python · Groq API (OpenAI-compatible) · SQLite · pandas

## Possible extensions

- Read the schema directly from the database instead of hard-coding it in the prompt, so the description can't drift from the real tables.
- Add few-shot examples to the prompt to improve accuracy on complex joins.
- Wrap the system in a small web interface (e.g. Streamlit) for interactive use.
