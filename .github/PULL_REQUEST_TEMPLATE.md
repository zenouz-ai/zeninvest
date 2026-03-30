## Summary
<!-- What does this PR do? Why? -->

## Changes
<!-- List the key changes made -->

## Checklist
- [ ] All existing tests pass (`poetry run pytest -v`)
- [ ] New functionality is covered by tests
- [ ] Type annotations are correct (`poetry run mypy src/`)
- [ ] Affected docs updated (README.md, CLAUDE.md, docs/ — see CLAUDE.md maintenance table)
- [ ] No API keys, secrets, or `.env` contents included
- [ ] New features have a disable switch and fall back to current behaviour
- [ ] Alembic migration added if schema changed (`poetry run alembic revision --autogenerate -m "..."`)

## Test plan
<!-- How did you verify this works? -->

## Related issues
<!-- Closes #... -->
