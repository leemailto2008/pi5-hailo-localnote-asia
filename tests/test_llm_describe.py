import httpx

import llm_backend as lb


def test_describe_names_exceptions_with_empty_message():
    # httpx.ReadTimeout 的 str() 是空字串：日誌原本只印出「failed (attempt 1):」(11-11)。
    assert lb._describe(httpx.ReadTimeout("")) == "ReadTimeout"
    assert lb._describe(lb.LLMError("HTTP 500: boom")) == "LLMError: HTTP 500: boom"
    assert lb._describe(None) == "unknown error"
