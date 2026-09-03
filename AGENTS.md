# CSV Profiling Phase

The minimal chat foundation is complete. The current scope is CSV upload and profiling.

- Use Python 3.12, uv, Pydantic AI, OpenRouter, and the built-in Web Chat UI.
- Keep code small, explicit, and readable. Keep application modules at the project root.
- Expose one profiling tool: profile_csv(uploaded_file_id) -> DatasetProfile.
- The tool imports the CSV into local DuckDB, computes statistics with fixed code,
  calls one semantic profiler agent, combines the results in Python, and saves the profile.
- Use typed dependencies, Pydantic output models, and normal agent delegation.
- Pass the parent run's usage to the semantic agent. Never let LLM output replace measured statistics.
- Keep values from every oversized column out of both agents' prompts; include only metadata and counts. Always exclude WKT values.
- Keep uploaded files and DuckDB data in the ignored data/ directory.
- Put CSV upload in the built-in chat by using its documented custom HTML source. No separate upload page or React application.
- Preserve the existing CodeMode, Advisor, and TemporalDurability capabilities.
- Temporal support remains installed and attached; no workflow or worker exists yet.
- Do not add chart rendering, a planner, additional agents, Docker, or a generic orchestration layer.
- Verify known statistics, failed semantic runs, persistence, uploads, and a real OpenRouter browser run.

Run with:

    uv run uvicorn main:app --host 127.0.0.1 --port 7932 --reload

Run tests with:

    uv run python -m pytest
