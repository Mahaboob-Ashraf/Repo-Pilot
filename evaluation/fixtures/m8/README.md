# M8 frozen local evaluation fixtures

This directory is evaluation-only. Repository files are synthetic, frozen inputs;
`cases.json` contains scoring labels that must never cross the retrieval or
ContextPack construction boundary.

The small repositories are not production samples or SWE-bench tasks. They exist
to compare the current RepoPilot retrieval variants and exercise deterministic
safety boundaries without network access.
