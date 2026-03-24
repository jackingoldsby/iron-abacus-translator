"""
API Client Wrappers

Simple wrappers for OpenAI and Anthropic APIs, plus unified LLM abstraction.
"""

from .openai_client import get_client as get_openai_client, quick_chat as openai_chat
from .anthropic_client import get_client as get_anthropic_client, quick_chat as anthropic_chat
from .llm_client import LLMClient, LLMRequest, LLMResponse, OpenAILLMClient, AnthropicLLMClient, llm_chat_json
from .llm_config import get_llm_client

__all__ = [
    # Legacy exports
    'get_openai_client',
    'openai_chat',
    'get_anthropic_client',
    'anthropic_chat',
    # New abstraction
    'LLMClient',
    'LLMRequest',
    'LLMResponse',
    'OpenAILLMClient',
    'AnthropicLLMClient',
    'llm_chat_json',
    'get_llm_client',
]
