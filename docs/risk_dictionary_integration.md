# Risk Dictionary Integration

The backend compliance flow now runs a risk-expression detector against the
generated draft text. It supplements the existing ComplianceAgent result and
does not replace the existing rule, RAG, or validation flow.

## Detector

- Module: `backend/src/tools/risk_dictionary_detector.py`
- Public functions:
  - `detect_risk_expressions(text, limit=None)`
  - `detect_semantic_risk_patterns(text)`
  - `detect_compliance_risks(text, limit=None)`
- DB table: `risk_expression_dictionary_test`

The detector reads active rows from the dictionary table when `is_active` exists.
If the column does not exist, all rows are treated as usable. The code first
checks `information_schema.columns`, then selects only columns present in the
actual schema.

## Environment

The detector uses existing environment configuration only. It checks these
variables in order:

1. `DATABASE_URL`
2. `NEON_DATABASE_URL`
3. `POSTGRES_URL`
4. `DB_API_URL`
5. `PGHOST`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGPORT`
6. `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `POSTGRES_PORT`, `POSTGRES_SSLMODE`

Secrets are not logged. If DB connection, table lookup, or dependency loading
fails, the detector logs a warning and returns empty findings.

## Workflow Output

`compliance_node` adds these fields to graph state and API responses:

- `dictionary_findings`
- `semantic_findings`
- `risk_dictionary_summary`

These findings are review context. `needs_context_review: true` means the text
around the match includes limiting, exclusionary, or negating language and should
not be treated as a final violation without contextual review.

## Tests

Run the focused detector tests:

```bash
python -m pytest backend/tests/test_risk_dictionary_detector.py -q
```
