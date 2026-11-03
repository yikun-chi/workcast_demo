# Stack Overflow Developer Survey, AI tool use by group: NO-GO

Not an instance (no `instance.yaml`); kept as the record of why the case was not built.

- Data: the public results of the 2023-2026 surveys, downloaded by `ingest/audit/fetch.py` (hashes in
  `manifests/sources.json`; licence ODbL 1.0, cell contents DbCL 1.0).
- Audit: `ingest/audit/inspect_columns.py` prints each wave's AI question, its answers and the grouping columns.

Why NO-GO:

1. Only three waves ask the same question. 2023, 2024 and 2025 ask "Do you currently use AI tools in your development
   process?" (2025 splits "Yes" by frequency, which can be collapsed). 2026 asks a different question, "Do you
   currently use AI tools or AI agents in your role at work?", as a multi-select of tool types with "I don't use AI
   tools", shown to a narrower set of respondents.
2. 2026 also replaces the role question (`DevType`) with a new one (`Role`) with different categories.
3. With three comparable waves there are two forecastable waves (2024 from 2023, 2025 from 2023-2024). The protocol
   reserves the first quarter of the cutoffs, at least two, for development, so no consistently measured held-out
   wave remains. Scoring 2026 against a model of the earlier question would score a change of wording, not adoption.
4. Each wave is a new self-selected sample, not a panel, so group shares also move with who answers.

Revisit when a later wave repeats the 2026 question, giving at least two waves of the new measure after the
development waves.
