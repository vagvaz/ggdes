# ggdes/llm/

## Responsibility

LLM provider abstraction layer. Provides a unified interface for multiple LLM backends
(Anthropic, OpenAI, Ollama, Custom OpenAI-compatible, OpencodeZen), retry logic with
exponential backoff, structured output generation (JSON/XML), and API key resolution.
All LLM calls in GGDes go through this module.

## Design

### Provider Hierarchy

```
LLMProvider (ABC)
├── AnthropicProvider          — Anthropic Claude (XML structured outputs)
├── BaseOpenAICompatibleProvider (ABC)
│   ├── OpenAIProvider         — OpenAI API (JSON structured outputs)
│   ├── OllamaProvider         — Local Ollama models (JSON, thinking toggle)
│   ├── CustomOpenAIProvider   — Generic OpenAI-compatible endpoint (XML)
│   └── OpencodeZenProvider    — OpencodeZen gateway (JSON, model family routing)
```

### Key Components

#### `LLMFactory` (`factory.py`)

Central factory with two creation methods:

- **`create(provider, model_name, api_key, ...)`** — Resolves API key, looks up
  provider class in `PROVIDERS` dict, instantiates and returns the provider.
- **`from_config(config)`** — Creates a provider from a `GGDesConfig` object,
  extracting `model.provider`, `model.model_name`, `model.api_key`,
  `model.base_url`, and `model.structured_format`.
- **`list_providers()`** — Returns list of supported provider names.
- **`get_opencodezen_info(model_name)`** — Returns routing info (family, endpoint).

Provider mapping:
```python
PROVIDERS = {
    "anthropic":    AnthropicProvider,
    "openai":       OpenAIProvider,
    "ollama":       OllamaProvider,
    "opencodezen":  OpencodeZenProvider,
    "custom":       CustomOpenAIProvider,
}
```

#### `LLMProvider` (abstract base)

Core interface methods:

| Method | Description |
|---|---|
| `chat(messages, temperature, max_tokens)` | Generate from conversation context |
| `generate(prompt, system_prompt, temperature, max_tokens)` | Generate from prompt |
| `async_chat(messages, temperature, max_tokens)` | Async version of `chat()` — default runs sync in thread-pool executor; providers override for true async I/O |
| `async_generate(prompt, system_prompt, temperature, max_tokens)` | Async version of `generate()` — default runs sync in thread-pool executor; providers override for true async I/O |
| `generate_structured(prompt, response_model, system_prompt, temperature, max_retries)` | Generate structured output matching a Pydantic model |

#### `retry_on_failure` decorator

Wraps `chat()` and `generate()` methods on every provider. Parameters:
- `max_retries: int = 3`
- `initial_delay: float = 1.0` (seconds)
- `max_delay: float = 60.0`
- `exponential_base: float = 2.0`
- `retryable_exceptions: tuple = (Exception,)`

Adds jitter (uniform 0–10% of delay) to prevent thundering herd. Logs each attempt
with provider, model, method, duration, and error details.

#### `resolve_api_key`

Resolves API key from multiple patterns:
- Literal string: returned as-is
- `${VAR_NAME}`: reads from environment variable
- `env:VAR_NAME`: reads from environment variable
- Provider-specific fallback env vars: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `OPENCODEZEN_API_KEY`/`ZEN_API_KEY`, `CUSTOM_API_KEY`
- Ollama returns `"ollama"` (dummy key)

#### Structured Output Generation

`generate_structured()` implements a retry loop for parsing:

1. Appends format instructions (JSON schema or XML template) to the system prompt
2. Calls `generate()` and attempts to parse the response
3. On failure, builds a correction prompt with the parse error and original response
4. Retries with slightly increased temperature (min(t+0.1, 1.0))
5. Falls through to raise `ValueError` after `max_retries` attempts

JSON parsing (`_parse_json_response`):
- Strips markdown code fences
- Attempts direct `json.loads()`
- Falls through to `_repair_json()` which handles:
  - Single quotes → double quotes
  - Trailing commas
  - JavaScript-style comments
  - Unquoted keys
  - Extraneous text after JSON object
- Falls through to regex extraction of `{...}`

XML parsing (`_parse_xml_response`):
- Strips markdown fences and `<?xml?>` declarations
- Parses with `xml.etree.ElementTree`
- Converts to dict (lists identified by `<item>` children)
- Validates with Pydantic

Format selection (`_get_output_format`):

| Provider | Default Format |
|---|---|
| AnthropicProvider | `xml` |
| CustomOpenAIProvider | `xml` |
| OpenAIProvider | `json` |
| OllamaProvider | `json` |
| OpencodeZenProvider | `json` |
| Override | `structured_format` parameter (`"auto"`, `"json"`, `"xml"`) |

### Provider Details

#### `AnthropicProvider`
- Uses the official `anthropic` SDK
- Extracts system message from message list (Anthropic's `system` param is separate)
- Supports custom `base_url`
- Default format: XML

#### `BaseOpenAICompatibleProvider`
- Shared `chat()` and `generate()` using OpenAI `chat.completions.create`
- Subclasses implement `_get_client()` for client construction
- Default format: JSON

#### `OllamaProvider`
- Extends `BaseOpenAICompatibleProvider`
- `_get_extra_body()` disables thinking by default (`{"options": {"think": False}, "reasoning_effort": "none"}`)
- Re-enabled via `enable_thinking=True` constructor parameter
- Uses `ollama` as dummy API key

#### `CustomOpenAIProvider`
- Base URL is **required** (raises `ValueError` if missing)
- Uses XML as default format
- Connects to any OpenAI-compatible API

#### `OpencodeZenProvider`
- Detects model family from name (claude → anthropic, gemini → google, else → openai)
- Routes to different base URLs per family:
  - openai: `https://opencode.ai/zen/v1`
  - anthropic: `https://opencode.ai/zen/v1/messages`
  - google: `https://opencode.ai/zen/v1`

## Flow

```
Application code
    ↓
LLMFactory.create(provider, model_name, api_key, ...)
    ↓
resolve_api_key(api_key, provider) → resolves ${VAR} / env:VAR / fallback
    ↓
AnthropicProvider / OpenAIProvider / OllamaProvider / etc.
    ↓
  retry_on_failure decorator (3 attempts, exponential backoff + jitter)
    ↓
  ┌─ sync path ────────────────────────────┐
  │  chat() / generate() → API call        │
  │  generate_structured (if used):        │
  │    prompt → add format instructions →   │
  │    generate() → parse → validate →      │
  │    retry if needed                      │
  └─────────────────────────────────────────┘
  ┌─ async path ───────────────────────────┐
  │  async_chat() / async_generate()       │
  │    ├─ default: asyncio.to_thread(…)    │
  │    │   (runs sync in thread-pool)       │
  │    └─ overridden: true async I/O       │
  │  (no structured variant yet)           │
  └─────────────────────────────────────────┘
    ↓
  Text / Pydantic model instance returned
```

## Integration

- **`LLMFactory.from_config()`** is called by `ggdes.agents.base.AgentBase` to
  create LLM providers for each analysis agent.
- **`retry_on_failure`** decorates `chat()` and `generate()` on every concrete provider class.
- **Tools system** (`ggdes/tools/chat_with_tools.py`) wraps `llm.chat()` with
  tool-calling loop.
- **`resolve_api_key`** is used by `LLMFactory.create()` and can be used standalone.
- **`detect_model_family`** is used by `OpencodeZenProvider` for endpoint routing.
- **`ConversationContext`** (from `conversation.py`) wraps provider instances for
  conversation management with token estimation.
