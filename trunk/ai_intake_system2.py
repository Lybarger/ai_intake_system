#!/usr/bin/env python3

import os
import json
import uuid
import logging
from typing import Dict, Any
from typing_extensions import TypedDict
from typing import Annotated
from pydantic import BaseModel, Field, ValidationError

# --- Langchain / LangGraph Imports ---
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# Optional: For rendering the final state graph (e.g. in Jupyter or saving PNG)
try:
    from IPython.display import Image, display
except ImportError:
    Image = None
    display = None

# -------------------------------------------------------------------
# Setup Logging
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='ai_intake_system.log',
    filemode='w'
)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# 1) Load the prompt texts from .md files
# -------------------------------------------------------------------
def load_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

PROMPT_150_PATH = "prompts/Prompt_0150_Get_Familiar.md"
PROMPT_200_PATH = "prompts/Prompt_0200_Depression_Severity.md"

prompt_150 = load_prompt(PROMPT_150_PATH)
prompt_200 = load_prompt(PROMPT_200_PATH)

# -------------------------------------------------------------------
# 2) Initialize an OpenAI-based LLM
# -------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
api_key_path = os.path.join(script_dir, '..', '..', 'OPENAI_API_KEY')
with open(api_key_path, 'r') as key_file:
    api_key = key_file.read().strip()
os.environ["OPENAI_API_KEY"] = api_key

llm = ChatOpenAI(temperature=0, model_name="gpt-4o")

# -------------------------------------------------------------------
# 3) Define a typed dictionary for conversation state
# -------------------------------------------------------------------
class State(TypedDict):
    messages: Annotated[list, add_messages]
    stage: int

# -------------------------------------------------------------------
# 4) Define the expected output schema with Pydantic
# -------------------------------------------------------------------
class Demographics(BaseModel):
    age: str = Field("", description="Client's age")
    gender: str = Field("", description="Client's gender")

class IntakeOutput(BaseModel):
    response: str = Field(..., description="Your reply, question, or acknowledgment")
    status: str = Field(..., description='Must be one of "in-progress", "complete", "stop", or "alert"')
    medical_history: Dict[str, Any] = Field(
        ..., description="Medical history dictionary containing demographics"
    )

# -------------------------------------------------------------------
# 5) Create a function to parse the LLM output using the Pydantic model
# -------------------------------------------------------------------
def parse_output(ai_message: AIMessage) -> Dict[str, Any]:
    """
    Attempt to parse the AIMessage content as JSON using a Pydantic model.
    If parsing fails, fallback to a default structure.
    """
    try:
        # Try to load as JSON first
        raw_data = json.loads(ai_message.content)
        # Validate and convert using the Pydantic model
        parsed = IntakeOutput.parse_obj(raw_data)
        return parsed.dict()
    except (json.JSONDecodeError, ValidationError) as e:
        logger.error("Parsing failed: %s", e)
        # Fallback: Return a default structure with the raw content as the response
        return {
            "response": ai_message.content,
            "status": "in-progress",
            "medical_history": {
                "demographics": {
                    "age": "",
                    "gender": ""
                }
            }
        }

# -------------------------------------------------------------------
# 6) Define chain functions (LangGraph nodes) for each stage
# -------------------------------------------------------------------
def chain_150_get_familiar(state: State) -> Dict[str, Any]:
    messages = [SystemMessage(content=prompt_150)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}

def chain_200_depression_severity(state: State) -> Dict[str, Any]:
    messages = [SystemMessage(content=prompt_200)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}

# -------------------------------------------------------------------
# 7) Decide how to transition between stages
# -------------------------------------------------------------------
def decide_next_stage(state: State) -> str:
    messages = state["messages"]
    if not messages:
        return f"stage_{state['stage']}"
    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage):
        return f"stage_{state['stage']}"
    
    parsed = parse_output(last_msg)
    status = parsed.get("status", "").lower()

    if status == "stop":
        result_node = END
    elif status == "alert":
        result_node = END
    elif status == "complete":
        if state["stage"] == 150:
            result_node = "stage_200"
        elif state["stage"] == 200:
            result_node = END
    else:
        result_node = f"stage_{state['stage']}"
    
    logger.debug("DEBUG next_stage = %r", result_node)
    return result_node

# -------------------------------------------------------------------
# 8) Create the graph with the relevant nodes
# -------------------------------------------------------------------
memory = MemorySaver()
workflow = StateGraph(State)
workflow.add_node("stage_150", chain_150_get_familiar)
workflow.add_node("stage_200", chain_200_depression_severity)

@workflow.add_node
def dummy_terminal(state: State):
    return {"messages": []}

workflow.add_conditional_edges("stage_150", decide_next_stage, ["stage_200", "stage_150", END])
workflow.add_conditional_edges("stage_200", decide_next_stage, [END, "stage_200"])
workflow.add_edge(START, "stage_150")
graph = workflow.compile(checkpointer=memory)

if display is not None:
    from IPython.display import Image
    display(Image(graph.get_graph().draw_mermaid_png()))
    with open("graph.png", "wb") as f:
        f.write(graph.get_graph().draw_mermaid_png())

# -------------------------------------------------------------------
# 9) Interactive conversation loop with logging and parsing
# -------------------------------------------------------------------
def main():
    state_data = {
        "messages": [],
        "stage": 150
    }
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("Welcome to the AI Intake System. Type 'q' or 'Q' to quit.\n")
    logger.info("System started. Awaiting user input.")

    while True:
        user_input = input("User (q/Q to quit): ")
        if user_input.lower() == "q":
            print("AI: Conversation ended.")
            logger.info("User requested to quit. Conversation ended.")
            break

        logger.info("User input: %s", user_input)
        state_data["messages"].append(HumanMessage(content=user_input))

        # Use a single-step invocation to get one AI response per input
        state_data = graph.invoke(state_data, config=config)
        ai_msg = state_data["messages"][-1]
        if isinstance(ai_msg, AIMessage):
            parsed_output = parse_output(ai_msg)
            print(f"AI: {parsed_output}")
            logger.info("AI output: %s", parsed_output)

        next_stage = decide_next_stage(state_data)
        if next_stage == END:
            print("AI: All stages complete. Goodbye.")
            logger.info("Workflow reached END. Conversation complete.")
            break
        elif next_stage.startswith("stage_"):
            state_data["stage"] = int(next_stage.split("_")[1])
            logger.debug("Updated stage to: %s", state_data["stage"])

if __name__ == "__main__":
    main()
