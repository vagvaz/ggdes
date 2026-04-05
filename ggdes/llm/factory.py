"""LLM factory for managing different providers with Instructor for structured outputs."""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional, TypeVar

from pydantic import BaseModel, create_model

T = TypeVar("T", bound=BaseModel)

# Model family detection for OpencodeZen
MODEL_FAMILY_PREFIXES = {
    "anthropic": ["claude"],
    "google": ["gemini"],
    "openai": ["gpt", "glm", "kimi", "qwen", "minimax", "big-pickle"],
}


def detect_model_family(model_name: str) -> str:
    """Detect the model family from model name for OpencodeZen routing.

    Args:
        model_name: Model identifier (e.g., "gpt-4", "claude-opus-4")

    Returns:
        Family name: "anthropic", "google", or "openai"
    """
    model_lower = model_name.lower()
    for family, prefixes in MODEL_FAMILY_PREFIXES.items():
        if any(prefix in model_lower for prefix in prefixes):
            return family
    return "openai"  # Default to OpenAI-compatible


def resolve_api_key(api_key: str | None, provider: str) -> str | None:
    """Resolve API key with ${VAR} and env:VAR patterns.

    Args:
        api_key: API key string, potentially with env var patterns
        provider: Provider name for default env var fallback

    Returns:
        Resolved API key or None if not found
    """
    if isinstance(api_key, str):
        s = api_key.strip()
        # ${VAR} pattern
        if s.startswith("${") and s.endswith("}") and len(s) > 3:
            var = s[2:-1].strip()
            return os.getenv(var)
        # env:VAR pattern
        if s.lower().startswith("env:"):
            var = s.split(":", 1)[1].strip()
            return os.getenv(var)
        return api_key

    # Default env var fallback by provider
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY")
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    if provider == "opencodezen":
        return os.getenv("OPENCODEZEN_API_KEY") or os.getenv("ZEN_API_KEY")
    if provider == "ollama":
        return "ollama"  # Ollama doesn't need API key

    return None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        """Initialize provider.

        Args:
            api_key: API key for the provider
            model_name: Model name/identifier
            **kwargs: Additional provider-specific options
        """
        self.api_key = api_key
        self.model_name = model_name
        self.options = kwargs

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text from prompt.

        Args:
            prompt: User prompt
            system_prompt: System prompt/instructions
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text
        """
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> T:
        """Generate structured output matching Pydantic model.

        Args:
            prompt: User prompt
            response_model: Pydantic model class for expected output
            system_prompt: System prompt/instructions
            temperature: Sampling temperature
            max_retries: Maximum retries on validation failure

        Returns:
            Instance of response_model
        """
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider with Instructor for structured outputs."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self._client = None

    def _get_client(self):
        """Lazy-load Anthropic client with Instructor."""
        if self._client is None:
            import anthropic
            import instructor

            client = anthropic.Anthropic(api_key=self.api_key)
            self._client = instructor.from_anthropic(client)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using Anthropic Claude (without Instructor)."""
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)

        messages = [{"role": "user", "content": prompt}]

        response = client.messages.create(
            model=self.model_name,
            max_tokens=max_tokens or 4096,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )

        return response.content[0].text

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> T:
        """Generate structured output using Instructor."""
        client = self._get_client()

        messages = [{"role": "user", "content": prompt}]
        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})

        return client.messages.create(
            model=self.model_name,
            max_tokens=4096,
            temperature=temperature,
            messages=messages,
            response_model=response_model,
            max_retries=max_retries,
        )


class OpenAIProvider(LLMProvider):
    """OpenAI provider with Instructor for structured outputs."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self._client = None

    def _get_client(self):
        """Lazy-load OpenAI client with Instructor."""
        if self._client is None:
            import instructor
            import openai

            client = openai.OpenAI(api_key=self.api_key)
            self._client = instructor.from_openai(client)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using OpenAI (without Instructor)."""
        import openai

        client = openai.OpenAI(api_key=self.api_key)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> T:
        """Generate structured output using Instructor."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            response_model=response_model,
            max_retries=max_retries,
        )


class OllamaProvider(LLMProvider):
    """Ollama local model provider using OpenAI-compatible endpoint with Instructor."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str = "http://localhost:11434/v1",
        **kwargs,
    ):
        super().__init__(api_key, model_name, **kwargs)
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        """Lazy-load Ollama client with Instructor (via OpenAI-compatible endpoint)."""
        if self._client is None:
            import instructor
            import openai

            client = openai.OpenAI(
                api_key="ollama",  # Ollama doesn't validate API keys
                base_url=self.base_url,
            )
            self._client = instructor.from_openai(client)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using Ollama (without Instructor)."""
        import openai

        client = openai.OpenAI(
            api_key="ollama",
            base_url=self.base_url,
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> T:
        """Generate structured output using Instructor."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            response_model=response_model,
            max_retries=max_retries,
        )


class OpencodeZenProvider(LLMProvider):
    """OpencodeZen gateway provider with model family detection and Instructor."""

    # OpencodeZen endpoints by model family
    ENDPOINTS = {
        "openai": "https://opencode.ai/zen/v1",
        "anthropic": "https://opencode.ai/zen/v1/messages",
        "google": "https://opencode.ai/zen/v1",
    }

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self.family = detect_model_family(model_name)
        self.base_url = self._get_base_url(self.family)
        self._client = None

    def _get_base_url(self, family: str) -> str:
        """Get OpenAI-compatible base URL for the family."""
        endpoint = self.ENDPOINTS.get(family, self.ENDPOINTS["openai"])
        # ChatOpenAI expects base_url like "https://host/v1"
        normalized = endpoint.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized
        return f"{normalized}/v1"

    def _get_client(self):
        """Lazy-load OpencodeZen client with Instructor."""
        if self._client is None:
            import instructor
            import openai

            client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
            self._client = instructor.from_openai(client)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using OpencodeZen (without Instructor)."""
        import openai

        client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_retries: int = 3,
    ) -> T:
        """Generate structured output using Instructor."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            response_model=response_model,
            max_retries=max_retries,
        )


class LLMFactory:
    """Factory for creating LLM providers with API key resolution."""

    PROVIDERS = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
        "opencodezen": OpencodeZenProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        model_name: str,
        api_key: str,
        **kwargs,
    ) -> LLMProvider:
        """Create an LLM provider instance with API key resolution.

        Args:
            provider: Provider name (anthropic, openai, ollama, opencodezen)
            model_name: Model name
            api_key: API key (supports ${VAR} and env:VAR patterns)
            **kwargs: Additional provider options

        Returns:
            LLMProvider instance

        Raises:
            ValueError: If provider is not supported or API key missing
        """
        # Resolve API key with patterns
        resolved_key = resolve_api_key(api_key, provider)
        if not resolved_key:
            raise ValueError(
                f"Missing API key for {provider}. "
                f"Set it in config, environment variable, "
                f"or use pattern like ${{VAR}} or env:VAR"
            )

        provider_class = cls.PROVIDERS.get(provider.lower())
        if not provider_class:
            supported = ", ".join(cls.PROVIDERS.keys())
            raise ValueError(
                f"Unsupported provider: {provider}. Supported: {supported}"
            )

        return provider_class(resolved_key, model_name, **kwargs)

    @classmethod
    def from_config(cls, config) -> LLMProvider:
        """Create provider from GGDes config.

        Args:
            config: GGDesConfig instance

        Returns:
            LLMProvider instance
        """
        return cls.create(
            provider=config.model.provider,
            model_name=config.model.model_name,
            api_key=config.model.api_key,
        )

    @classmethod
    def list_providers(cls) -> list[str]:
        """List supported providers.

        Returns:
            List of provider names
        """
        return list(cls.PROVIDERS.keys())

    @classmethod
    def get_opencodezen_info(cls, model_name: str) -> dict:
        """Get OpencodeZen routing info for a model.

        Args:
            model_name: Model name to check

        Returns:
            Dict with family, endpoint, etc.
        """
        family = detect_model_family(model_name)
        endpoint = OpencodeZenProvider.ENDPOINTS.get(
            family, OpencodeZenProvider.ENDPOINTS["openai"]
        )
        base_url = (
            endpoint.rstrip("/") if endpoint.endswith("/v1") else f"{endpoint}/v1"
        )

        return {
            "model_name": model_name,
            "family": family,
            "endpoint": endpoint,
            "base_url": base_url,
        }
