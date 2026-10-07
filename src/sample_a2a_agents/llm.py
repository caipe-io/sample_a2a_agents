"""OpenAI-compatible model configuration for the standalone examples."""

import os

from langchain_openai import ChatOpenAI


def get_llm() -> ChatOpenAI:
    """Use OpenAI or a compatible endpoint such as LiteLLM."""
    model = os.getenv("OPENAI_MODEL_NAME", "").strip()
    if not model:
        raise ValueError("Set OPENAI_MODEL_NAME to a model available at your endpoint.")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise ValueError("Set OPENAI_API_KEY for your model endpoint.")
    endpoint = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_ENDPOINT") or "https://api.openai.com/v1"
    return ChatOpenAI(model=model, base_url=endpoint, timeout=120, max_retries=2)
