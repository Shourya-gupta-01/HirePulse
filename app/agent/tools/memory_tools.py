from langchain_core.tools import tool
from app.memory.ltm import ltm_store

@tool
def save_user_memory(fact: str) -> str:
    """Save an important fact, user preference, instruction, or personal detail about the user into long-term memory for future conversations."""
    result = ltm_store.add_memory(fact)
    mem_id = result.get("id")
    action = result.get("action")

    if not mem_id:
        return "Failed to save memory: empty content."

    if action == "exact_duplicate":
        return f"Preference already recorded in long-term memory: '{fact}'"
    elif action == "updated":
        return f"Updated existing long-term memory preference to: '{fact}'"
    return f"Saved new fact to long-term memory: '{fact}'"


@tool
def recall_user_memories(topic: str) -> str:
    """Search long-term memory for past historical facts, detailed notes, past job applications, or preferences not already present in the active user profile."""
    memories = ltm_store.search_memories(topic)
    if not memories:
        return "No relevant long-term memories found for this topic."
    return "\n".join(f"- {m}" for m in memories)
