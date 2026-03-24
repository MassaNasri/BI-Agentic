import os
import time

from openai import APIError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3n-e4b-it:free")
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
    default_headers={
        "HTTP-Referer": "http://localhost",
        "X-Title": "BI Voice Agent",
    },
)


def call_llm(prompt: str) -> str:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not configured")

    delay_seconds = 1.0
    last_error: Exception | None = None

    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM returned an empty response")
            return content
        except AuthenticationError as exc:
            raise ValueError(f"OpenRouter authentication failed: {exc}") from exc
        except RateLimitError as exc:
            last_error = exc
            if attempt >= LLM_MAX_RETRIES:
                break
            time.sleep(delay_seconds)
            delay_seconds *= 2
        except APITimeoutError as exc:
            last_error = exc
            if attempt >= LLM_MAX_RETRIES:
                break
            time.sleep(delay_seconds)
            delay_seconds *= 2
        except APIError as exc:
            last_error = exc
            if attempt >= LLM_MAX_RETRIES:
                break
            time.sleep(delay_seconds)
            delay_seconds *= 2
        except Exception as exc:
            raise RuntimeError(f"LLM service error: {exc}") from exc

    if isinstance(last_error, RateLimitError):
        raise RuntimeError(f"LLM rate limit exceeded after retries: {last_error}") from last_error
    if isinstance(last_error, APITimeoutError):
        raise RuntimeError(f"LLM timeout after retries: {last_error}") from last_error
    if isinstance(last_error, APIError):
        raise RuntimeError(f"LLM API error after retries: {last_error}") from last_error
    raise RuntimeError("LLM call failed after retries")
