# Skill: Write Tests

**Purpose:** Reliable regression and integration coverage. **Use when:** adding tests or changing behavior.

**Procedure:**
1. Identify positive, negative and edge cases from the acceptance criteria; add the smallest stable tests.
2. Always cover authorization: user A cannot read, change or delete user B's conversations, files, memos, tasks or embeddings.
3. Fake the OpenAI client, web search, clock and file storage; no live network calls.
4. For audio: cover size limits, chunking, failed transcription and retry behavior.
5. For reminders: cover due, not yet due, done and deleted tasks with a fixed clock.
6. Run targeted tests first, then the full suite inside Docker.

**Validation:** State exact commands, actual pass/fail and known untested paths.

**Constraints:** Never fake test results or bypass authorization in mocks.
