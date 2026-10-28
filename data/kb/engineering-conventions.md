# Engineering conventions

## Pull request reviews
Review comments must reference a file and line, state the concrete failure, and propose a fix. Do not post style-only comments; the linter handles style.

## CI failures
When CI fails, read the failing test name and the assertion first. Reproduce before proposing a change. Never suggest skipping or deleting a test to get green.
