"""LLM factory for managing different providers."""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional


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
        output_schema: dict[str, Any],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate structured output matching schema.

        Args:
            prompt: User prompt
            output_schema: JSON schema for expected output
            system_prompt: System prompt/instructions
            temperature: Sampling temperature

        Returns:
            Parsed structured output
        """
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self._client = None

    def _get_client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using Anthropic Claude."""
        client = self._get_client()

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
        output_schema: dict[str, Any],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate structured output using Anthropic."""
        import json

        # Add schema to system prompt
        structured_system = system_prompt or ""
        structured_system += (
            f"\n\nYou must respond with a JSON object matching this schema:\n"
            f"{json.dumps(output_schema, indent=2)}\n\n"
            f"Respond only with the JSON, no other text."
        )

        text = self.generate(prompt, structured_system, temperature, max_tokens=4096)

        # Extract JSON from response
        try:
            # Find JSON block if wrapped in markdown
            if "```json" in text:
                json_start = text.find("```json") + 7
                json_end = text.find("```", json_start)
                text = text[json_start:json_end].strip()
            elif "```" in text:
                json_start = text.find("```") + 3
                json_end = text.find("```", json_start)
                text = text[json_start:json_end].strip()

            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse structured output: {e}\nResponse: {text}"
            )


class OpenAIProvider(LLMProvider):
    """OpenAI provider."""

    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self._client = None

    def _get_client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using OpenAI."""
        client = self._get_client()

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
        output_schema: dict[str, Any],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate structured output using OpenAI."""
        import json

        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Use response_format for structured output (OpenAI specific)
        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        text = response.choices[0].message.content
        return json.loads(text)


class OllamaProvider(LLMProvider):
    """Ollama local model provider."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str = "http://localhost:11434",
        **kwargs,
    ):
        # Ollama doesn't use API keys like cloud providers
        super().__init__("", model_name, **kwargs)
        self.base_url = base_url

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using Ollama."""
        import requests

        url = f"{self.base_url}/api/generate"

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt or "",
            "options": {
                "temperature": temperature,
            },
            "stream": False,
        }

        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        response = requests.post(url, json=payload)
        response.raise_for_status()

        return response.json()["response"]

    def generate_structured(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate structured output using Ollama."""
        import json

        # Add schema to system prompt
        structured_system = system_prompt or ""
        structured_system += (
            f"\n\nYou must respond with a JSON object matching this schema:\n"
            f"{json.dumps(output_schema, indent=2)}\n\n"
            f"Respond only with the JSON, no other text."
        )

        text = self.generate(prompt, structured_system, temperature)

        # Extract JSON
        try:
            if "```json" in text:
                json_start = text.find("```json") + 7
                json_end = text.find("```", json_start)
                text = text[json_start:json_end].strip()
            elif "```" in text:
                json_start = text.find("```") + 3
                json_end = text.find("```", json_start)
                text = text[json_start:json_end].strip()

            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse structured output: {e}\nResponse: {text}"
            )


class LLMFactory:
    """Factory for creating LLM providers."""

    PROVIDERS = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        model_name: str,
        api_key: str,
        **kwargs,
    ) -> LLMProvider:
        """Create an LLM provider instance.

        Args:
            provider: Provider name (anthropic, openai, ollama)
            model_name: Model name
            api_key: API key
            **kwargs: Additional provider options

        Returns:
            LLMProvider instance

        Raises:
            ValueError: If provider is not supported
        """
        provider_class = cls.PROVIDERS.get(provider.lower())
        if not provider_class:
            supported = ", ".join(cls.PROVIDERS.keys())
            raise ValueError(
                f"Unsupported provider: {provider}. Supported: {supported}"
            )

        return provider_class(api_key, model_name, **kwargs)

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
