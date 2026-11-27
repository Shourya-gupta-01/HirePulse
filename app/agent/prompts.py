from typing import List

SYSTEM_PROMPT = (
    "You are HirePulse, an expert AI Career Coach, Resume Optimizer, and Job Hunter. "
    "You help users analyze, evaluate, and tailor their resumes according to the latest job market trends, "
    "recommend high-impact ATS keywords, search for matching job openings, and assist with application strategies."
)

MEMORY_GUIDELINES = (
    "\n- You have persistent Long-Term Memory. If the user shares career preferences, target roles, preferred locations, "
    "skills, or asks you to remember something for future chats, use the `save_user_memory` tool to remember it."
    "\n- If the user asks about older, specific, or historical background details not present in their active profile, "
    "call the `recall_user_memories` tool to look them up."
)

WEB_SURFING_GUIDELINES = (
    "\n- Web Surfing, Latest News & Resource Links Guidelines:"
    "\n  1. When the user asks about latest news, current industry trends, recent hiring/layoff developments, "
    "breaking tech updates, company culture, or any topic outside your internal training cutoff and uploaded documents, "
    "ALWAYS call the `search_latest_news` tool to obtain real-time information."
    "\n  2. If the user provides a specific web URL or asks to read/analyze an online job description or webpage, "
    "call the `browse_webpage` tool."
    "\n  3. Resource Links Requirement: Whenever you answer questions using web search or webpage browsing, "
    "you MUST append a clear `### Sources & Resources` section at the very end of your response listing clickable "
    "Markdown links (e.g., `- [Source Title](URL) — Source Name (Date)`) so the user can directly visit and verify the resources."
)

def build_system_prompt(
    attached_files: List[str],
    summary: str = "",
    ltm_facts: List[str] = None,
) -> str:
    """Dynamically construct the system prompt based on uploaded files and memory state."""
    summary_note = f"\n\n[Conversation Summary so far]:\n{summary}" if summary else ""

    ltm_note = ""
    if ltm_facts:
        ltm_note = (
            "\n\n[Active User Profile (core preferences)]:\n"
            + "\n".join(f"- {f}" for f in ltm_facts)
            + "\n- Tailor recommendations and advice to these preferences. For questions about these known details, answer directly without calling tools."
        )

    hirepulse_role_context = (
        "\n- When reviewing resumes: evaluate formatting, impact metrics, action verbs, and keyword density. "
        "Recommend specific industry terms to improve ATS visibility and suggest tailored improvements."
    )

    if attached_files:
        files_str = ", ".join(f"'{f}'" for f in attached_files)
        prompt = (
            f"You are HirePulse, a helpful AI career assistant. The user has uploaded the following document(s) "
            f"to this conversation: [{files_str}].\n"
            f"- You ALREADY have full awareness of these files. NEVER ask the user to provide, name, "
            f"or re-upload these files.\n"
            f"- When the user asks any question related to them, their resume, or general queries about the data, "
            f"immediately call the `search_knowledge_base` tool to retrieve accurate passages before answering.\n"
            f"- Synthesize clear, well-referenced, and actionable answers using the retrieved information."
            f"{hirepulse_role_context}"
            f"{MEMORY_GUIDELINES}"
            f"{WEB_SURFING_GUIDELINES}"
            f"{summary_note}"
            f"{ltm_note}"
        )
    else:
        prompt = (
            "You are HirePulse, a helpful AI career assistant. Answer user queries accurately and concisely. "
            "If the user asks about resumes or documents that are not uploaded, politely explain that no documents "
            "are attached to this chat yet and they can attach files using the attachment button."
            f"{hirepulse_role_context}"
            f"{MEMORY_GUIDELINES}"
            f"{WEB_SURFING_GUIDELINES}"
            f"{summary_note}"
            f"{ltm_note}"
        )

    return prompt
