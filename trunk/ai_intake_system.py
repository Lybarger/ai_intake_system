#!/usr/bin/env python3

import os
import json
import uuid
import logging
from typing import Dict, Any
from typing_extensions import TypedDict
from typing import Annotated

# --- Langchain / LangGraph Imports ---
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from pydantic import BaseModel, Field, ValidationError

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
    filemode='w'  # 'w' to overwrite each time, 'a' to append
)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# 1) Load the prompt texts from .md files (ID 150 and ID 200).
#    Adjust these paths if the files are located elsewhere.
# -------------------------------------------------------------------
def load_prompt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

PROMPT_150_PATH = "prompts/Prompt_0150_Get_Familiar2.md"
PROMPT_200_PATH = "prompts/Prompt_0200_Depression_Severity.md"


prompt_150 = load_prompt(PROMPT_150_PATH)
prompt_200 = load_prompt(PROMPT_200_PATH)

# -------------------------------------------------------------------
# 2) Initialize an OpenAI-based LLM
# -------------------------------------------------------------------
# Optionally load OPENAI_API_KEY from a file or environment variable:
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
    # "messages" are the conversation messages so far.
    messages: Annotated[list, add_messages]
    # "stage" tracks which stage ID we are currently in, e.g. 150 or 200.
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
# 4) Define chain functions (LangGraph nodes) for each stage
# -------------------------------------------------------------------

def chain_150_get_familiar(state: State) -> Dict[str, Any]:
    """
    This node handles ID 150 "Get Familiar". 
    It prepends the prompt_150 system message to the conversation 
    and invokes the LLM to produce a new AI message.
    """
    # Prepend the ID 150 system message
    messages = [SystemMessage(content=prompt_150)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


def chain_200_depression_severity(state: State) -> Dict[str, Any]:
    """
    This node handles ID 200 "Depression Severity". 
    It prepends the prompt_200 system message to the conversation 
    and invokes the LLM to produce a new AI message.
    """
    # Prepend the ID 200 system message
    messages = [SystemMessage(content=prompt_200)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


# -------------------------------------------------------------------
# 5) Decide how to transition between stages.
#    We'll parse the AI's JSON output (if possible) to see if "status" == "complete".
#    If stage 150 is complete, move on to 200; if stage 200 is complete, end.
# -------------------------------------------------------------------
def parse_json_from_ai(ai_message: AIMessage) -> Dict[str, Any]:
    """
    Attempt to parse the AIMessage content as JSON.
    If parsing fails, return an empty dict.
    """
    try:
        return json.loads(ai_message.content)
    except (json.JSONDecodeError, TypeError):
        return {}

def parse_json(message: str) -> Dict[str, Any]:
    """
    Attempt to parse the AIMessage content as JSON.
    If parsing fails, return an empty dict.
    """
    try:
        return json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return {}


# -------------------------------------------------------------------
# 5) Create a function to parse the LLM output using the Pydantic model
# -------------------------------------------------------------------
def strip_markdown_code(text: str) -> str:
    """
    Remove markdown code block formatting (e.g. triple backticks) from the text.
    """
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        # Remove the first line (which may be ```json)
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        # Remove the last line (the closing backticks)
        lines = lines[:-1]
    return "\n".join(lines).strip()

def parse_output(ai_message: AIMessage) -> Dict[str, Any]:
    """
    Attempt to parse the AIMessage content as JSON using a Pydantic model.
    If parsing fails, fallback to a default structure.
    """
    try:
        # Remove markdown code block formatting if present
        cleaned_content = strip_markdown_code(ai_message.content)
        # Try to load as JSON first
        raw_data = json.loads(cleaned_content)
        # Validate and convert using the Pydantic model
        # parsed = IntakeOutput.parse_obj(raw_data)
        parsed = IntakeOutput.model_validate(raw_data)

        return parsed.model_dump()

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


def decide_next_stage(state: State) -> str:
    """
    This function inspects the last AI message:
    - If the last message has "status" == "complete" and we're in stage 150, go to stage_200.
    - If the last message has "status" == "complete" and we're in stage 200, go to END.
    - Otherwise, remain in the same stage node.
    If the user tries to quit or "status" == "stop", we also end.
    If there's an alert, you might handle that separately as well.
    """
    messages = state["messages"]
    if not messages:
        # No messages yet, remain in the current stage
        return f"stage_{state['stage']}"

    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage):
        # If the last message isn't from the AI, remain in current stage
        return f"stage_{state['stage']}"

    # Parse the AI's JSON
    parsed = parse_json_from_ai(last_msg)
    status = parsed.get("status", "").lower()

    if status == "stop":
        result_node = END
    elif status == "alert":
        # Example: you could route to a specialized "alert" node, or just end
        result_node = END

    elif status == "complete":
        if state["stage"] == 150:
            # Move from 150 to 200
            result_node = "stage_200"
        elif state["stage"] == 200:
            # Move from 200 to end
            result_node = END

    else:
        # Otherwise, keep the same stage
        result_node = f"stage_{state['stage']}"
    
    print("DEBUG next_stage =", repr(result_node))
    return result_node


# -------------------------------------------------------------------
# 6) Create the graph with the relevant nodes
# -------------------------------------------------------------------
memory = MemorySaver()
workflow = StateGraph(State)

# Add our nodes (chains) to the workflow
workflow.add_node("stage_150", chain_150_get_familiar)
workflow.add_node("stage_200", chain_200_depression_severity)

@workflow.add_node
def dummy_terminal(state: State):
    """Terminal node: no further messages."""
    return {"messages": []}

# We define conditional edges from stage_150 -> decide_next_stage -> ...
workflow.add_conditional_edges(
    "stage_150", decide_next_stage, ["stage_200", "stage_150", END]
)

workflow.add_conditional_edges(
    "stage_200", decide_next_stage, [END, "stage_200"]
)

workflow.add_edge(START, "stage_150")

# Compile the graph
graph = workflow.compile(checkpointer=memory)


# -------------------------------------------------------------------
# 7) [Optional] Render and save the graph if running in Jupyter or local environment
# -------------------------------------------------------------------
if display is not None:
    from IPython.display import Image
    display(Image(graph.get_graph().draw_mermaid_png()))

    with open("graph.png", "wb") as f:
        f.write(graph.get_graph().draw_mermaid_png())


# -------------------------------------------------------------------
# 8) Interactive conversation loop
# -------------------------------------------------------------------
def main():
    # Initialize an empty conversation and start at stage=150
    state_data = {
        "messages": [],
        "stage": 150
    }

    # Provide a unique thread ID or config if needed
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("Welcome to the AI Intake System. Type 'q' or 'Q' to quit.\n")

    while True:

        # Prompt user for input
        user_input = input("User (q/Q to quit): ")
        if user_input in {"q", "Q"}:
            print("AI: Conversation ended.")
            break

        # Add the user's message to the conversation
        state_data["messages"].append(HumanMessage(content=user_input))

        # Now run the state machine in streaming mode
        output_iter = graph.stream(state_data, config=config, stream_mode="updates")
        
        # Keep track of the final output from this turn
        last_output = None
        for i, last_output in enumerate(output_iter):
            print(f'\ninteration = {i}')

            # The workflow updates 'state_data' behind the scenes with new messages
            ai_msg = next(iter(last_output.values()))["messages"][-1]
        
            # print('ai_msg,  type', type(ai_msg))
            # print('ai_msg, value', ai_msg)
            # # "Pretty-print" the AI's text
            # print('content,  type', type(ai_msg.content))
            # print('content, value', ai_msg.content)
            
            d = parse_output(ai_msg)
            
            print(f"response:   {d['response']}")
            print(f"status:     {d['status']}")
            print(f"med hx:     {d['medical_history']}")

        # If there's an updated stage
        # (We check if the stage changed by checking the key "stage" in state_data.)
        # It's changed automatically by the conditional edges in LangGraph if we
        # used "stage" in a custom function, but let's just confirm:
        # (For simplicity we rely on the node transitions themselves.)

        # # If last_output included "END", that means we are done
        # if last_output is not None:
        #     # If the node is "END" or we detect we ended, break
        #     if "END" in last_output:
        #         print("AI: All stages complete. Goodbye.")
        #         break

if __name__ == "__main__":
    main()

