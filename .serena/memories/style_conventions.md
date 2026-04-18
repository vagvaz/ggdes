## Coding Style & Conventions
- Formatting and linting enforced by Ruff; lint rules include E, F, I, N, W, UP, B, C4, SIM with line length checking disabled (E501 ignored).
- Docstrings follow Google style (`tool.ruff.lint.pydocstyle.convention = google`).
- Mypy runs in strict mode (python version 3.10) with `warn_return_any` and `warn_unused_ignores`; skills folders and tests excluded, but core package must remain fully typed.
- Preference for explicit type hints across codebase; third-party stubs installed for libraries lacking types.
- Tests use pytest (async support via pytest-asyncio when needed).
- Skills scripts are excluded from lint/type checks; rest of package should adhere to standard conventions.
