class Collections:
    """
    Single source of truth for all MongoDB collection names.
    Change a name here and it updates everywhere.
    """
    # Stores every LLM-generated response with its validation scores
    RESPONSES = "llm_responses"

    # Stores every raw feedback event (thumbs up/down + text)
    FEEDBACK = "feedback_events"

    # Stores processed feedback signals written to MemPalace
    MEMPALACE_SIGNALS = "mempalace_signals"

    # Stores distilled facts and memory updates from feedback
    SEMANTIC_FACTS = "semantic_facts"