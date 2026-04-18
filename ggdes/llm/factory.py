"""LLM factory for managing different providers with structured outputs."""

import functools
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

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
    if provider == "custom":
        return os.getenv("CUSTOM_API_KEY")

    return None


def retry_on_failure(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that adds retry logic with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff calculation
        retryable_exceptions: Tuple of exception types that should trigger a retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Extract provider info for logging
            provider_name = ""
            model_name = ""
            if args and isinstance(args[0], LLMProvider):
                provider_name = args[0].__class__.__name__
                model_name = args[0].model_name

            method_name = func.__name__
            logger.info(
                "LLM call starting | provider={} model={} method={}",
                provider_name,
                model_name,
                method_name,
            )
            call_start = time.time()

            last_exception: BaseException | None = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    call_duration = time.time() - call_start
                    logger.info(
                        "LLM call completed | provider={} model={} method={} "
                        "duration={:.1f}s attempts={}",
                        provider_name,
                        model_name,
                        method_name,
                        call_duration,
                        attempt + 1,
                    )
                    return result
                except retryable_exceptions as e:
                    last_exception = e
                    call_duration = time.time() - call_start

                    if attempt < max_retries:
                        # Calculate delay with exponential backoff
                        delay = min(
                            initial_delay * (exponential_base**attempt),
                            max_delay,
                        )

                        # Add jitter to prevent thundering herd
                        jitter = random.uniform(0, delay * 0.1)
                        actual_delay = delay + jitter

                        logger.warning(
                            "LLM call failed (attempt {}/{}) | provider={} model={} "
                            "method={} duration={:.1f}s error_type={} error={} | retrying in {:.1f}s...",
                            attempt + 1,
                            max_retries + 1,
                            provider_name,
                            model_name,
                            method_name,
                            call_duration,
                            type(e).__name__,
                            e,
                            actual_delay,
                        )
                        time.sleep(actual_delay)
                    else:
                        logger.error(
                            "LLM call failed after {} attempts | provider={} model={} "
                            "method={} duration={:.1f}s error_type={} error={}",
                            max_retries + 1,
                            provider_name,
                            model_name,
                            method_name,
                            call_duration,
                            type(e).__name__,
                            e,
                        )

            # All retries exhausted, raise the last exception
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("All retries exhausted but no exception captured")

        return wrapper

    return decorator


def _model_to_xml_schema(model_class: type[BaseModel], root_name: str = "root") -> str:
    """Convert Pydantic model to XML schema representation.

    Args:
        model_class: Pydantic model class
        root_name: Root element name

    Returns:
        XML schema string
    """
    schema = model_class.model_json_schema()
    properties = schema.get("properties", {})

    lines = [f"<{root_name}>"]

    for field_name, field_info in properties.items():
        field_type = field_info.get("type", "string")
        if field_type == "array":
            item_type = field_info.get("items", {}).get("type", "string")
            lines.append(f"  <{field_name}>")
            lines.append(f"    <item>{item_type}</item>")
            lines.append("    <!-- more items... -->")
            lines.append(f"  </{field_name}>")
        elif field_type == "object":
            lines.append(f"  <{field_name}>")
            lines.append("    <!-- nested object fields -->")
            lines.append(f"  </{field_name}>")
        else:
            lines.append(f"  <{field_name}>{field_type}</{field_name}>")

    lines.append(f"</{root_name}>")
    return "\n".join(lines)


def _model_to_json_schema(model_class: type[BaseModel]) -> str:
    """Convert Pydantic model to JSON schema representation.

    Args:
        model_class: Pydantic model class

    Returns:
        JSON schema string
    """
    schema = model_class.model_json_schema()
    return json.dumps(schema, indent=2)


def _add_structured_instructions(
    system_prompt: str | None,
    response_model: type[T],
    output_format: str = "json",
    examples: list[dict[str, Any]] | None = None,
) -> str:
    """Add structured output instructions to system prompt.

    Args:
        system_prompt: Original system prompt
        response_model: Pydantic model class for expected output
        output_format: 'json' or 'xml'
        examples: Optional list of example outputs

    Returns:
        Updated system prompt with format instructions
    """
    if output_format == "xml":
        xml_schema = _model_to_xml_schema(response_model)
        instructions = f"""

You must respond with valid XML that matches this schema:

{xml_schema}

Important XML formatting rules:
1. Use proper XML syntax with opening and closing tags
2. All field values must be enclosed in their tags
3. Do not include XML declaration (<?xml version="1.0"?>)
4. Do not use markdown code blocks (```xml) - return raw XML only
5. Ensure all special characters are properly escaped in text content
6. All required fields must be present"""

        if examples:
            instructions += "\n\nExamples:\n"
            for i, example in enumerate(examples, 1):
                # Convert example dict to XML
                xml_lines = ["<root>"]
                for key, value in example.items():
                    if isinstance(value, list):
                        xml_lines.append(f"  <{key}>")
                        for item in value:
                            xml_lines.append(f"    <item>{item}</item>")
                        xml_lines.append(f"  </{key}>")
                    else:
                        xml_lines.append(f"  <{key}>{value}</{key}>")
                xml_lines.append("</root>")
                instructions += f"\nExample {i}:\n" + "\n".join(xml_lines)

    else:  # json
        json_schema = _model_to_json_schema(response_model)
        instructions = f"""

You must respond with valid JSON that matches this schema:

{json_schema}

Important JSON formatting rules:
1. Use proper JSON syntax with double quotes for keys and string values
2. Do not use markdown code blocks (```json) - return raw JSON only
3. Ensure all special characters in strings are properly escaped
4. All required fields must be present"""

        if examples:
            instructions += "\n\nExamples:\n"
            for i, example in enumerate(examples, 1):
                instructions += f"\nExample {i}:\n{json.dumps(example, indent=2)}"

    if system_prompt:
        return system_prompt + instructions
    return instructions.strip()


def _create_correction_prompt(
    original_response: str,
    parse_error: str,
    output_format: str = "json",
) -> str:
    """Create a corrective prompt for the LLM when parsing fails.

    Args:
        original_response: The LLM's previous response that failed parsing
        parse_error: The error message from parsing
        output_format: 'json' or 'xml'

    Returns:
        Corrective prompt
    """
    if output_format == "xml":
        return f"""Your previous response could not be parsed as valid XML.

Error: {parse_error}

Your previous response:
{original_response}

Please provide a corrected response in valid XML format. Remember:
1. Use proper XML tags with matching opening and closing tags
2. No markdown formatting (no ```xml blocks)
3. No XML declaration header
4. Escape special characters: & becomes &amp;, < becomes &lt;, > becomes &gt;
5. Ensure all fields are present with proper values

The expected XML structure must match the original schema you were given.
Provide only the corrected XML response:"""
    else:
        return f"""Your previous response could not be parsed as valid JSON.

Error: {parse_error}

Your previous response:
{original_response}

Please provide a corrected response in valid JSON format. Remember:
1. Use double quotes for all keys and string values
2. No markdown formatting (no ```json blocks)
3. Properly escape special characters in strings
4. Ensure all fields are present with proper values

The expected JSON structure must match the original schema you were given.
Provide only the corrected JSON response:"""


def _strip_markdown_code_blocks(text: str) -> str:
    """Remove markdown code block fences from response text.

    Args:
        text: Raw response text, potentially wrapped in ``` fences

    Returns:
        Text with code block fences removed
    """
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3].strip()
        elif "```" in text:
            text = text[: text.rfind("```")].strip()
    return text


def _parse_xml_response(response_text: str, response_model: type[T]) -> T:
    """Parse and validate XML response into Pydantic model.

    Args:
        response_text: Raw LLM response text
        response_model: Pydantic model class for expected output

    Returns:
        Instance of response_model

    Raises:
        ValueError: If XML parsing or validation fails
    """
    text = response_text.strip()

    # Remove markdown code blocks if present
    text = _strip_markdown_code_blocks(text)

    # Remove XML declaration if present
    text = re.sub(r"<\?xml[^?]*\?>\s*", "", text, flags=re.IGNORECASE)

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error: {e}") from e

    # Convert XML to dict
    def xml_to_dict(element: ET.Element) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for child in element:
            if len(child) == 0:
                # Leaf node
                result[child.tag] = child.text or ""
            else:
                # Has children
                if all(c.tag == "item" for c in child):
                    # It's a list
                    result[child.tag] = [
                        c.text or "" for c in child if c.text is not None
                    ]
                else:
                    result[child.tag] = xml_to_dict(child)
        return result

    data = xml_to_dict(root)

    # Validate with Pydantic
    try:
        return response_model.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Response validation failed: {e}") from e


def _parse_json_response(response_text: str, response_model: type[T]) -> T:
    """Parse and validate JSON response into Pydantic model.

    Args:
        response_text: Raw LLM response text
        response_model: Pydantic model class for expected output

    Returns:
        Instance of response_model

    Raises:
        ValueError: If JSON parsing or validation fails
    """
    text = response_text.strip()

    # Remove markdown code blocks if present
    text = _strip_markdown_code_blocks(text)

    # Try to find JSON object/array in the text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON from response: {e}") from e
        else:
            raise ValueError(
                f"No JSON object found in response: {text[:200]}"
            ) from None

    # Validate with Pydantic
    try:
        return response_model.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Response validation failed: {e}") from e


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        structured_format: str = "auto",
        **kwargs: Any,
    ):
        """Initialize provider.

        Args:
            api_key: API key for the provider
            model_name: Model name/identifier
            base_url: Optional base URL for the API endpoint
            structured_format: 'auto', 'json', or 'xml'
            **kwargs: Additional provider-specific options
        """
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.structured_format = structured_format
        self.options = kwargs

    def _get_output_format(self) -> str:
        """Determine output format for structured responses.

        Returns:
            'json' or 'xml'
        """
        if self.structured_format != "auto":
            return self.structured_format
        # Auto-detect based on provider
        return self._get_default_format()

    def _get_default_format(self) -> str:
        """Get default output format for this provider.

        Returns:
            'json' or 'xml'
        """
        return "json"  # Default to JSON

    def _get_examples(self, response_model: type[T]) -> list[dict[str, Any]]:
        """Get example outputs for the response model.

        Args:
            response_model: Pydantic model class

        Returns:
            List of example dicts
        """
        # Try to get examples from model's Config or docstring
        model_config = getattr(response_model, "model_config", {})
        json_schema_extra: dict[str, Any] = (
            model_config.get("json_schema_extra", {})
            if isinstance(model_config, dict)
            else {}
        )
        examples: list[dict[str, Any]] = json_schema_extra.get("examples", [])
        if examples:
            return examples

        # Create a minimal example from schema
        schema = response_model.model_json_schema()
        properties = schema.get("properties", {})
        example: dict[str, Any] = {}
        for field_name, field_info in properties.items():
            field_type = field_info.get("type", "string")
            if field_type == "string":
                example[field_name] = f"example_{field_name}"
            elif field_type == "integer":
                example[field_name] = 42
            elif field_type == "number":
                example[field_name] = 3.14
            elif field_type == "boolean":
                example[field_name] = True
            elif field_type == "array":
                example[field_name] = ["item1", "item2"]
            elif field_type == "object":
                example[field_name] = {}
            else:
                example[field_name] = None

        return [example]

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from conversation context.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text
        """
        ...

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
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
        ...

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str | None = None,
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
        output_format = self._get_output_format()
        examples = self._get_examples(response_model)
        model_name = response_model.__name__

        logger.info(
            "Structured LLM call starting | provider={} model={} response_model={} "
            "format={} max_retries={}",
            self.__class__.__name__,
            self.model_name,
            model_name,
            output_format,
            max_retries,
        )
        call_start = time.time()

        # Add format instructions to system prompt
        full_system_prompt = _add_structured_instructions(
            system_prompt, response_model, output_format, examples
        )

        last_error: BaseException | None = None
        previous_response: str | None = None

        for attempt in range(max_retries + 1):
            try:
                if attempt == 0:
                    # First attempt - use original prompt
                    current_prompt = prompt
                else:
                    # Retry with correction prompt
                    assert previous_response is not None
                    assert last_error is not None
                    correction_prompt = _create_correction_prompt(
                        previous_response, str(last_error), output_format
                    )
                    current_prompt = correction_prompt
                    logger.warning(
                        "Structured output parsing failed, asking LLM to correct "
                        "(attempt {}/{}) | provider={} model={} response_model={}",
                        attempt + 1,
                        max_retries + 1,
                        self.__class__.__name__,
                        self.model_name,
                        model_name,
                    )

                response_text = self.generate(
                    prompt=current_prompt,
                    system_prompt=full_system_prompt if attempt == 0 else None,
                    temperature=temperature,
                    max_tokens=None,
                )
                previous_response = response_text

                # Parse response
                if output_format == "xml":
                    result = _parse_xml_response(response_text, response_model)
                else:
                    result = _parse_json_response(response_text, response_model)

                call_duration = time.time() - call_start
                logger.info(
                    "Structured LLM call completed | provider={} model={} "
                    "response_model={} duration={:.1f}s attempts={}",
                    self.__class__.__name__,
                    self.model_name,
                    model_name,
                    call_duration,
                    attempt + 1,
                )
                return result

            except (
                ValueError,
                json.JSONDecodeError,
                ET.ParseError,
                ValidationError,
            ) as e:
                last_error = e
                if attempt < max_retries:
                    # Increase temperature for variety on retry
                    temperature = min(temperature + 0.1, 1.0)
                else:
                    call_duration = time.time() - call_start
                    logger.error(
                        "Structured output failed after {} attempts | provider={} "
                        "model={} response_model={} duration={:.1f}s error_type={} error={}",
                        max_retries + 1,
                        self.__class__.__name__,
                        self.model_name,
                        model_name,
                        call_duration,
                        type(e).__name__,
                        e,
                    )

        raise ValueError(f"Failed to generate valid structured output: {last_error}")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider with XML structured outputs."""

    def _get_default_format(self) -> str:
        """Anthropic models work best with XML."""
        return "xml"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        structured_format: str = "auto",
        **kwargs: Any,
    ):
        super().__init__(api_key, model_name, base_url, structured_format, **kwargs)

    @retry_on_failure(  # type: ignore[type-var]
        max_retries=3,
        initial_delay=1.0,
        retryable_exceptions=(Exception,),
    )
    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text using full conversation context."""
        import anthropic

        # Explicitly construct Anthropic client with proper types
        if self.base_url:
            client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        else:
            client = anthropic.Anthropic(api_key=self.api_key)

        # Extract system message if present
        system = None
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg.get("content")
            else:
                chat_messages.append(
                    {
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", ""),
                    }
                )

        # Build request parameters with proper typing
        request_params: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
            "messages": chat_messages,
        }
        if system is not None:
            request_params["system"] = system

        response = client.messages.create(**request_params)

        # Only TextBlock has .text attribute, filter appropriately
        content_blocks = response.content
        if content_blocks and hasattr(content_blocks[0], "text"):
            text_value: str = content_blocks[0].text
            return text_value
        return ""

    @retry_on_failure(  # type: ignore[type-var]
        max_retries=3,
        initial_delay=1.0,
        retryable_exceptions=(Exception,),
    )
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text using Anthropic Claude."""
        import anthropic

        # Explicitly construct Anthropic client with proper types
        if self.base_url:
            client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        else:
            client = anthropic.Anthropic(api_key=self.api_key)

        messages = [{"role": "user", "content": prompt}]

        # Build request parameters with proper typing
        request_params: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt is not None:
            request_params["system"] = system_prompt

        response = client.messages.create(**request_params)

        # Only TextBlock has .text attribute, filter appropriately
        content_blocks = response.content
        if content_blocks and hasattr(content_blocks[0], "text"):
            text_value: str = content_blocks[0].text
            return text_value
        return ""


class BaseOpenAICompatibleProvider(LLMProvider):
    """Base class for OpenAI-compatible providers.

    Provides shared chat() and generate() implementations for providers
    that use the OpenAI chat.completions API (OpenAI, Ollama, Custom, OpencodeZen).
    Subclasses only need to implement _get_client() and optionally _get_default_format().
    """

    def _get_client(self) -> Any:
        """Get OpenAI-compatible client. Must be implemented by subclasses."""
        raise NotImplementedError

    @retry_on_failure(  # type: ignore[type-var]
        max_retries=3,
        initial_delay=1.0,
        retryable_exceptions=(Exception,),
    )
    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text using full conversation context."""
        client = self._get_client()

        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content  # type: ignore[no-any-return]

    @retry_on_failure(  # type: ignore[type-var]
        max_retries=3,
        initial_delay=1.0,
        retryable_exceptions=(Exception,),
    )
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from prompt."""
        client = self._get_client()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response.choices[0].message.content  # type: ignore[no-any-return]


class OpenAIProvider(BaseOpenAICompatibleProvider):
    """OpenAI provider with JSON structured outputs."""

    def _get_default_format(self) -> str:
        """OpenAI models work best with JSON."""
        return "json"

    def _get_client(self) -> Any:
        """Get OpenAI client."""
        import openai

        client_kwargs: dict[str, str] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        return openai.OpenAI(**client_kwargs)  # type: ignore[arg-type]


class OllamaProvider(BaseOpenAICompatibleProvider):
    """Ollama local model provider using OpenAI-compatible endpoint."""

    def _get_default_format(self) -> str:
        """Ollama models typically work best with JSON."""
        return "json"

    def _get_client(self) -> Any:
        """Get OpenAI-compatible client for Ollama."""
        import openai

        return openai.OpenAI(
            api_key="ollama",  # Ollama doesn't validate API keys
            base_url=self.base_url,
        )


class CustomOpenAIProvider(BaseOpenAICompatibleProvider):
    """Custom OpenAI-compatible API provider using XML structured outputs.

    This provider allows connecting to any OpenAI-compatible endpoint
    (e.g., local LLM servers, custom API gateways, third-party providers)
    by specifying a custom base_url and API key.

    Example:
        provider = CustomOpenAIProvider(
            api_key="your-api-key",
            model_name="custom-model",
            base_url="https://api.custom-llm.com/v1"
        )
    """

    def _get_default_format(self) -> str:
        """Custom providers typically work best with XML for reliability."""
        return "xml"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str,
        structured_format: str = "auto",
        **kwargs: Any,
    ):
        """Initialize custom OpenAI-compatible provider.

        Args:
            api_key: API key for authentication
            model_name: Model identifier
            base_url: Base URL for the OpenAI-compatible API (required)
            structured_format: 'auto', 'json', or 'xml'
            **kwargs: Additional provider options
        """
        if not base_url:
            raise ValueError("base_url is required for CustomOpenAIProvider")
        super().__init__(api_key, model_name, base_url, structured_format, **kwargs)

    def _get_client(self) -> Any:
        """Get OpenAI client."""
        import openai

        return openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )


class OpencodeZenProvider(BaseOpenAICompatibleProvider):
    """OpencodeZen gateway provider with JSON structured outputs."""

    def _get_default_format(self) -> str:
        """OpencodeZen typically routes to various models, use JSON as common format."""
        return "json"

    # OpencodeZen endpoints by model family
    ENDPOINTS = {
        "openai": "https://opencode.ai/zen/v1",
        "anthropic": "https://opencode.ai/zen/v1/messages",
        "google": "https://opencode.ai/zen/v1",
    }

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str | None = None,
        structured_format: str = "auto",
        **kwargs: Any,
    ):
        super().__init__(api_key, model_name, base_url, structured_format, **kwargs)
        self.family = detect_model_family(model_name)
        self.base_url = base_url or self._get_base_url(self.family)

    def _get_base_url(self, family: str) -> str:
        """Get OpenAI-compatible base URL for the family."""
        endpoint = self.ENDPOINTS.get(family, self.ENDPOINTS["openai"])
        # ChatOpenAI expects base_url like "https://host/v1"
        normalized = endpoint.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized
        return f"{normalized}/v1"

    def _get_client(self) -> Any:
        """Get OpenAI client for OpencodeZen."""
        import openai

        return openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )


class LLMFactory:
    """Factory for creating LLM providers with API key resolution."""

    PROVIDERS = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
        "opencodezen": OpencodeZenProvider,
        "custom": CustomOpenAIProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        model_name: str,
        api_key: str,
        structured_format: str = "auto",
        **kwargs: Any,
    ) -> LLMProvider:
        """Create an LLM provider instance with API key resolution.

        Args:
            provider: Provider name (anthropic, openai, ollama, opencodezen, custom)
            model_name: Model name
            api_key: API key (supports ${VAR} and env:VAR patterns)
            structured_format: 'auto', 'json', or 'xml'
            **kwargs: Additional provider options (e.g., base_url)

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

        return provider_class(  # type: ignore[no-any-return]
            resolved_key, model_name, structured_format=structured_format, **kwargs
        )

    @classmethod
    def from_config(cls, config: Any) -> LLMProvider:
        """Create provider from GGDes config.

        Args:
            config: GGDesConfig instance

        Returns:
            LLMProvider instance
        """
        kwargs: dict[str, str] = {}
        if config.model.base_url:
            kwargs["base_url"] = config.model.base_url

        # Get structured format from config
        structured_format = getattr(config.model, "structured_format", "auto")
        if hasattr(structured_format, "value"):
            structured_format = structured_format.value

        return cls.create(
            provider=config.model.provider,
            model_name=config.model.model_name,
            api_key=config.model.api_key,
            structured_format=structured_format,
            **kwargs,
        )

    @classmethod
    def list_providers(cls) -> list[str]:
        """List supported providers.

        Returns:
            List of provider names
        """
        return list(cls.PROVIDERS.keys())

    @classmethod
    def get_opencodezen_info(cls, model_name: str) -> dict[str, str]:
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
