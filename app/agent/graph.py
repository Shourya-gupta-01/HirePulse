import os
from typing import Optional

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.config import (
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    MODEL_NAME,
    OPENR_API,
    OPENROUTER_BASE_URL,
)

langfuse_handler = None
if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
    try:
        os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
        os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
        if LANGFUSE_HOST:
            os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST
            os.environ["LANGFUSE_BASE_URL"] = LANGFUSE_HOST

        from langfuse.langchain import CallbackHandler
        langfuse_handler = CallbackHandler()
    except Exception as exc:
        langfuse_handler = None
from app.memory.stm import (
    checkpointer,
    convo,
    get_thread_messages as stm_get_thread_messages,
    get_threads,
    safe_trim,
    update_summary,
)
from app.memory.ltm import ltm_store
from app.rag.pipeline import rag_system
from app.agent.tools import tools
from app.agent.prompts import build_system_prompt

# Initialize LLM
model = ChatOpenAI(
    model=MODEL_NAME,
    base_url=OPENROUTER_BASE_URL,
    request_timeout=60.0,
    api_key=OPENR_API,
    temperature=0.1,
    streaming=True,
)
model_with_tools = model.bind_tools(tools)


def Chatnode(state: convo, config: Optional[RunnableConfig] = None):
    msgs = list(state.get("messages", []))
    summary = state.get("summary", "")
    summarized_index = state.get("summarized_index", 0)

    thread_id = config.get("configurable", {}).get("thread_id") if config else None
    attached_files = rag_system.get_thread_files(thread_id) if thread_id else []

    # Filter out previous system messages so prompt dynamically updates
    non_system_msgs = [m for m in msgs if not isinstance(m, SystemMessage)]

    # Progressive summarization: runs on human turn start, batching unsummarized turns
    cutoff = max(0, len(non_system_msgs) - 8)
    if non_system_msgs and isinstance(non_system_msgs[-1], HumanMessage) and (cutoff - summarized_index >= 8):
        summary = update_summary(summary, non_system_msgs[summarized_index:cutoff], model=model)
        summarized_index = cutoff

    # Long-Term Memory (LTM): retrieve user-specific preferences and cross-thread memories
    latest_user_text = ""
    for m in reversed(non_system_msgs):
        if isinstance(m, HumanMessage):
            latest_user_text = m.content if isinstance(m.content, str) else str(m.content)
            break

    ltm_facts = ltm_store.search_memories(latest_user_text, k=3) if latest_user_text else []

    # Dynamic system prompt
    prompt = build_system_prompt(
        attached_files=attached_files,
        summary=summary,
        ltm_facts=ltm_facts,
    )

    # Token trimming: keep active window within token budget
    trimmed_msgs = safe_trim(non_system_msgs, max_tokens=2500)
    active_msgs = [SystemMessage(content=prompt)] + trimmed_msgs

    callbacks = [langfuse_handler] if langfuse_handler else []
    try:
        response = model_with_tools.invoke(active_msgs, config={"callbacks": callbacks})
    except Exception:
        if callbacks:
            response = model_with_tools.invoke(active_msgs)
        else:
            raise
    return {
        "messages": [response],
        "summary": summary,
        "summarized_index": summarized_index,
    }


# Build StateGraph
tool_node = ToolNode(tools)

graph = StateGraph(convo)
graph.add_node("Chatnode", Chatnode)
graph.add_node("tools", tool_node)

graph.add_edge(START, "Chatnode")
graph.add_conditional_edges("Chatnode", tools_condition)
graph.add_edge("tools", "Chatnode")

chatbot = graph.compile(checkpointer=checkpointer)


def get_thread_messages(thread_id: str) -> list[dict]:
    """Retrieve and format all messages for a given thread."""
    return stm_get_thread_messages(chatbot, thread_id)
