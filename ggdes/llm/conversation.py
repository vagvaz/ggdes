"""Conversation management for multi-turn agent interactions."""

import json
from pathlib import Path
from typing import Optional

from ggdes.schemas import StoragePolicy


def estimate_tokens(text: str) -> int:
    """Estimate token count for text.

    Rough approximation: ~4 characters per token for English text.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    return len(text) // 4


class ConversationContext:
    """Lightweight conversation manager for agent interactions."""

    def __init__(
        self,
        system_prompt: str,
        storage_policy: StoragePolicy = StoragePolicy.SUMMARY,
        max_tokens: int = 50000,
    ):
        """Initialize conversation context.

        Args:
            system_prompt: System prompt for the agent
            storage_policy: How to persist conversation
            max_tokens: Token threshold before compression
        """
        self.system_prompt = system_prompt
        self.messages: list[dict] = []  # Raw conversation history
        self.summaries: list[str] = []  # Progressive summaries
        self.storage_policy = storage_policy
        self.max_tokens = max_tokens
        self.current_tokens = 0

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation.

        Args:
            content: Message content
        """
        self.messages.append({"role": "user", "content": content})
        self.current_tokens += estimate_tokens(content) + 4  # ~4 tokens overhead

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the conversation.

        Args:
            content: Message content
        """
        self.messages.append({"role": "assistant", "content": content})
        self.current_tokens += estimate_tokens(content) + 4

        # Add to summaries for progressive context
        if len(content) > 200:
            # Truncate long responses for summary
            self.summaries.append(content[:200] + "...")
        else:
            self.summaries.append(content)

    def get_context_for_llm(self) -> list[dict]:
        """Get messages formatted for LLM API call.

        Returns:
            List of message dicts ready for LLM
        """
        if self.should_compress():
            return self.get_compressed_context()
        return [{"role": "system", "content": self.system_prompt}] + self.messages

    def should_compress(self) -> bool:
        """Check if conversation exceeds token threshold.

        Returns:
            True if compression needed
        """
        return self.current_tokens > self.max_tokens

    def get_compressed_context(self) -> list[dict]:
        """Compress conversation to fit within token limits.

        Strategy: Keep system prompt, summarize older messages,
        keep last 5 turns in full.

        Returns:
            Compressed message list
        """
        if len(self.messages) <= 5:
            # Not enough history to compress meaningfully
            return [{"role": "system", "content": self.system_prompt}] + self.messages

        # Keep last 5 exchanges in full
        recent_messages = self.messages[-10:]  # 5 user + 5 assistant = 10 messages

        # Summarize older messages
        older_messages = self.messages[:-10]
        summary = self._summarize_turns(older_messages)

        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": f"Previous conversation summary: {summary}"},
        ] + recent_messages

    def _summarize_turns(self, turns: list[dict]) -> str:
        """Summarize a list of conversation turns.

        Args:
            turns: List of message dicts

        Returns:
            Summary string
        """
        # Simple extraction of key points
        user_questions = []
        assistant_points = []

        for msg in turns:
            if msg["role"] == "user":
                # Extract first sentence or first 100 chars
                content = msg["content"]
                if len(content) > 100:
                    user_questions.append(content[:100] + "...")
                else:
                    user_questions.append(content)
            else:
                # Extract first sentence from assistant responses
                content = msg["content"]
                first_sentence = (
                    content.split(".")[0] if "." in content else content[:100]
                )
                assistant_points.append(first_sentence)

        summary_parts = []
        if user_questions:
            summary_parts.append(f"Questions asked: {len(user_questions)}")
        if assistant_points:
            key_points = "; ".join(assistant_points[:3])  # First 3 points
            summary_parts.append(f"Key findings: {key_points}")

        return (
            " | ".join(summary_parts)
            if summary_parts
            else "Prior conversation occurred"
        )

    def save(self, kb_path: Path) -> None:
        """Persist conversation based on storage policy.

        Args:
            kb_path: Path to save conversation data
        """
        kb_path.mkdir(parents=True, exist_ok=True)

        if self.storage_policy == StoragePolicy.RAW:
            # Save complete conversation history
            raw_path = kb_path / "conversation_raw.json"
            raw_path.write_text(
                json.dumps(
                    {
                        "system_prompt": self.system_prompt,
                        "messages": self.messages,
                        "total_tokens": self.current_tokens,
                    },
                    indent=2,
                )
            )
        elif self.storage_policy == StoragePolicy.SUMMARY:
            # Save summaries only
            summary_path = kb_path / "conversation_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "system_prompt": self.system_prompt,
                        "summaries": self.summaries,
                        "message_count": len(self.messages),
                        "total_tokens": self.current_tokens,
                    },
                    indent=2,
                )
            )
        # StoragePolicy.NONE: don't save anything

    @classmethod
    def load(
        cls, kb_path: Path, storage_policy: Optional[StoragePolicy] = None
    ) -> "ConversationContext":
        """Load conversation from KB.

        Args:
            kb_path: Path to saved conversation
            storage_policy: Override storage policy (uses saved if None)

        Returns:
            ConversationContext instance
        """
        raw_path = kb_path / "conversation_raw.json"
        summary_path = kb_path / "conversation_summary.json"

        if raw_path.exists():
            # Load raw conversation
            data = json.loads(raw_path.read_text())
            ctx = cls(
                system_prompt=data["system_prompt"],
                storage_policy=storage_policy or StoragePolicy.RAW,
            )
            ctx.messages = data["messages"]
            ctx.current_tokens = data.get("total_tokens", 0)
            return ctx
        elif summary_path.exists():
            # Load summary and reconstruct minimal context
            data = json.loads(summary_path.read_text())
            ctx = cls(
                system_prompt=data["system_prompt"],
                storage_policy=storage_policy or StoragePolicy.SUMMARY,
            )
            ctx.summaries = data["summaries"]
            ctx.current_tokens = data.get("total_tokens", 0)
            # Cannot reconstruct full messages from summary
            # But we can note that prior conversation occurred
            if ctx.summaries:
                ctx.messages.append(
                    {
                        "role": "system",
                        "content": f"Previous conversation summary: {ctx.summaries[-1]}",
                    }
                )
            return ctx
        else:
            raise FileNotFoundError(f"No conversation found at {kb_path}")

    def get_summary(self) -> str:
        """Get a summary of the conversation.

        Returns:
            Summary string
        """
        if self.summaries:
            return self.summaries[-1]  # Most recent summary
        elif self.messages:
            # Generate quick summary from messages
            return self._summarize_turns(self.messages)
        return "No conversation history"
