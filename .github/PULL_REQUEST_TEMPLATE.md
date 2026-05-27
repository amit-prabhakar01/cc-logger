## What does this PR do?

<!-- One paragraph describing the change and why it's needed -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change
- [ ] Documentation update
- [ ] Refactor / cleanup

## Testing

- [ ] Tests pass (`make test`)
- [ ] Added/updated tests for new behaviour
- [ ] Tested with a real Claude Code session

## Checklist

- [ ] `log_session.py` stays within ~200 lines of core logic
- [ ] No network calls added to the hot path (hook must stay <50ms)
- [ ] Sensitive data redaction is not weakened
- [ ] `NO_CC_LOGS=1` escape hatch still works
- [ ] `schema_version` bumped if JSON output shape changed

## Related issues

Closes #
