# sysadmin-ai-tests

## Running Tests

Always use `run_tests.py` to run tests — never call pytest directly.

```bash
python3 run_tests.py unit          # Unit tests only
python3 run_tests.py integration   # Integration tests (parallel, one worker per OS)
python3 run_tests.py all           # Unit first, then integration
```

Integration tests require `DIGITALOCEAN_TOKEN` and `OPENAI_API_KEY` environment variables.
