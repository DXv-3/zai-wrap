"""
providers/  —  zai-wrap provider implementations

Each provider module exports a class with:
    available() -> bool          True if the required env var is set
    complete(prompt, model, system, max_tokens, temperature) -> (str, int)
        Returns (content_text, tokens_used)
        Raises on hard failure; caller handles fallback.
"""
