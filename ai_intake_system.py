import getpass
import json
import logging
import os
import uuid

from typing import List, Literal, Dict, Any, Annotated
from typing_extensions import TypedDict

from langchain_core.messages import SystemMessage, AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from pydantic import BaseModel, Field, ValidationError

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from IPython.display import Image, display


COMPLETE = 'complete'
IN_PROGRESS = 'in-progress'
ALERT = 'alert'
STOP = 'stop'

FIRST_NODE = 150

# -------------------------------------------------------------------
# Set up API key from file
# -------------------------------------------------------------------
# Determine the absolute path to the API key file located two directories above this script.
script_dir = os.path.dirname(os.path.abspath(__file__))
api_key_path = os.path.join(script_dir, '..', '..', 'OPENAI_API_KEY')

# Read the API key from the file, remove any extra whitespace, and set it as an environment variable.
with open(api_key_path, 'r') as key_file:
    api_key = key_file.read().strip()
os.environ["OPENAI_API_KEY"] = api_key


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

PROMPT_150_PATH = "prompts/Prompt_0150_Get_Familiar.md"
PROMPT_200_PATH = "prompts/Prompt_0200_Depression_Severity.md"
PROMPT_300_PATH = "prompts/Prompt_0300_Illness_History.md"
PROMPT_400_PATH = "prompts/Prompt_0400_Antidepressant_History.md"
PROMPT_500_PATH = "prompts/Prompt_0500_Current_Medications.md"
PROMPT_600_PATH = "prompts/Prompt_0600_Procedures.md"
PROMPT_700_PATH = "prompts/Prompt_0700_Suicide_Risk_Factors.md"
PROMPT_800_PATH = "prompts/Prompt_0800_Bipolar.md"
PROMPT_900_PATH = "prompts/Prompt_0900_Conversation_Completed.md"
PROMPT_1000_PATH = "prompts/Prompt_1000_Stop_Interaction.md"

prompt_150 = load_prompt(PROMPT_150_PATH)
prompt_200 = load_prompt(PROMPT_200_PATH)
prompt_300 = load_prompt(PROMPT_300_PATH)
prompt_400 = load_prompt(PROMPT_400_PATH)
prompt_500 = load_prompt(PROMPT_500_PATH)
prompt_600 = load_prompt(PROMPT_600_PATH)
prompt_700 = load_prompt(PROMPT_700_PATH)
prompt_800 = load_prompt(PROMPT_800_PATH)
prompt_900 = load_prompt(PROMPT_900_PATH)
prompt_1000 = load_prompt(PROMPT_1000_PATH)

# Prepend the system message (with the prompt_150) to the conversation messages.
# def get_messages_info(messages):
#     return [SystemMessage(content=prompt_150)] + messages

# -------------------------------------------------------------------
# Define a Pydantic model for prompt instructions.
# -------------------------------------------------------------------
class PromptInstructions(BaseModel):
    """Instructions on how to prompt the LLM."""
    objective: str
    variables: List[str]
    constraints: List[str]
    requirements: List[str]



# -------------------------------------------------------------------
# 4) Define the expected output schema with Pydantic
# -------------------------------------------------------------------

class IntakeOutput(BaseModel):
    response: str = Field(..., description="Your reply, question, or acknowledgment")
    status: str = Field(..., description='Must be one of "in-progress", "complete", "stop", or "alert"')
    medical_history: Dict[str, Any] = Field(
        ..., description="Medical history dictionary containing demographics"
    )


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



# -------------------------------------------------------------------
# Initialize Language Model (LLM) with tool binding
# -------------------------------------------------------------------
# Instantiate the ChatOpenAI LLM with a deterministic output (temperature=0).
# llm = ChatOpenAI(temperature=0)
llm = ChatOpenAI(temperature=0, model_name="gpt-4o")
# Bind the PromptInstructions tool to the LLM so it can parse prompt details.
llm_with_tool = llm.bind_tools([PromptInstructions])

# -------------------------------------------------------------------
# Define a chain to collect information based on user messages.
# -------------------------------------------------------------------
def chain_150_get_familiar(state):
    messages = [SystemMessage(content=prompt_150)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_200_depression_severity(state):
    messages = [SystemMessage(content=prompt_200)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_300_illness_history7(state):
    messages = [SystemMessage(content=prompt_300)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_400_antidepressant_history(state):
    messages = [SystemMessage(content=prompt_400)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_500_current_medications(state):
    messages = [SystemMessage(content=prompt_500)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_600_procedures(state):
    messages = [SystemMessage(content=prompt_600)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_700_suicide_risk_factors(state):
    messages = [SystemMessage(content=prompt_700)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_800_bipolar(state):
    messages = [SystemMessage(content=prompt_800)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_900_conversation_completed(state):
    messages = [SystemMessage(content=prompt_900)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

def chain_1000_stop_interaction(state):
    messages = [SystemMessage(content=prompt_1000)] + state["messages"]
    response = llm_with_tool.invoke(messages)
    return {"messages": [response]}

# -------------------------------------------------------------------
# Define a system prompt template for generating the final prompt.
# -------------------------------------------------------------------
prompt_system = """Based on the following requirements, write a good prompt template:

{reqs}"""

# -------------------------------------------------------------------
# Extract messages after the tool call to generate the prompt.
# -------------------------------------------------------------------
def get_prompt_messages(messages: list):
    tool_call = None
    other_msgs = []
    # Iterate through the messages to find the first AIMessage with tool_calls.
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            tool_call = m.tool_calls[0]["args"]
        # Skip any ToolMessages in the conversation.
        elif isinstance(m, ToolMessage):
            continue
        # After a tool call has been found, collect subsequent messages.
        elif tool_call is not None:
            other_msgs.append(m)
    # Construct a new list starting with a SystemMessage that uses the prompt_system template,
    # then appends the other messages.
    return [SystemMessage(content=prompt_system.format(reqs=tool_call))] + other_msgs

# -------------------------------------------------------------------
# Define a chain to generate the final prompt using the LLM.
# -------------------------------------------------------------------
def prompt_gen_chain(state):
    messages = get_prompt_messages(state["messages"])
    response = llm.invoke(messages)
    return {"messages": [response]}

# -------------------------------------------------------------------
# Define a function to decide the next state in the state graph.
# -------------------------------------------------------------------
def get_state(state):

    
    messages = state["messages"]
    
    last_message = messages[-1]
    parsed = parse_output(last_message)
    
    response = parsed['response']
    status = parsed['status']
    medical_history = parsed['medical_history']
    
    
    
    # If the last message is an AIMessage that contains a tool call, transition to "add_tool_message".
    # Stay in current node

    current_step = state["step"]


    if status == ALERT:
        return 'step_1000'
    elif status == STOP:
        return 'step_1000'
    elif status == COMPLETE:
        if current_step == 150:
            return "step_200"
        elif current_step == 200:
            return "step_300"
        elif current_step == 300:
            return "step_400"
        elif current_step == 400:
            return "step_500"
        elif current_step == 500:
            return "step_600"
        elif current_step == 600:
            return "step_700"
        elif current_step == 700:
            return "step_800"
        elif current_step == 800:
            return "step_900"
        elif current_step == 900:
            return END
        elif current_step == 1000:
            return END
    
    elif isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "add_tool_message"
    # If the last message is not from a human, consider the conversation ended.
    elif not isinstance(messages[-1], HumanMessage):
        return END

    return END

# -------------------------------------------------------------------
# Define a typed dictionary for the conversation state.
# -------------------------------------------------------------------
class State(TypedDict):
    # "messages" are the conversation messages so far.
    messages: Annotated[list, add_messages]
    # "step" tracks which step ID we are currently in, e.g. 150 or 200.
    step: int
    
# -------------------------------------------------------------------
# Initialize memory for checkpointing and create the workflow state graph.
# -------------------------------------------------------------------
memory = MemorySaver()
workflow = StateGraph(State)
workflow.add_node("step_150", chain_150_get_familiar) 
workflow.add_node("step_200", chain_200_depression_severity)
workflow.add_node("step_300", chain_300_illness_history7)
workflow.add_node("step_400", chain_400_antidepressant_history)
workflow.add_node("step_500", chain_500_current_medications)
workflow.add_node("step_600", chain_600_procedures)
workflow.add_node("step_700", chain_700_suicide_risk_factors)
workflow.add_node("step_800", chain_800_bipolar)
workflow.add_node("step_900", chain_900_conversation_completed)
workflow.add_node("step_1000", chain_1000_stop_interaction)
workflow.add_node("prompt", prompt_gen_chain) # Node for generating the final prompt.

# -------------------------------------------------------------------
# Add a node to the workflow that adds a tool message indicating prompt generation.
# -------------------------------------------------------------------
@workflow.add_node
def add_tool_message(state: State):
    return {
        "messages": [
            ToolMessage(
                content="Prompt generated!",
                # Reference the tool call ID from the last message in state.
                tool_call_id=state["messages"][-1].tool_calls[0]["id"],
            )
        ]
    }

# -------------------------------------------------------------------
# Define transitions between states in the state graph.
# -------------------------------------------------------------------
workflow.add_conditional_edges( \
    "step_150", get_state, ["add_tool_message", "step_150", "step_200", END])
workflow.add_conditional_edges( \
    "step_200", get_state, ["add_tool_message", "step_200", "step_300", END])
workflow.add_conditional_edges( \
    "step_300", get_state, ["add_tool_message", "step_300", "step_400", END])
workflow.add_conditional_edges( \
    "step_400", get_state, ["add_tool_message", "step_400", "step_500", END])
workflow.add_conditional_edges( \
    "step_500", get_state, ["add_tool_message", "step_500", "step_600", END])
workflow.add_conditional_edges( \
    "step_600", get_state, ["add_tool_message", "step_600", "step_700", END])
workflow.add_conditional_edges( \
    "step_700", get_state, ["add_tool_message", "step_700", "step_800", END])
workflow.add_conditional_edges( \
    "step_800", get_state, ["add_tool_message", "step_800", "step_900", END])
workflow.add_conditional_edges( \
    "step_900", get_state, ["add_tool_message", "step_900", END])
workflow.add_conditional_edges( \
    "step_1000", get_state, ["add_tool_message", END])


workflow.add_edge("add_tool_message", "prompt")
workflow.add_edge("prompt", END)
workflow.add_edge(START, f"step_{FIRST_NODE}")
# Compile the workflow into a graph with memory checkpointing.
graph = workflow.compile(checkpointer=memory)

# -------------------------------------------------------------------
# Render and save the state graph visualization.
# -------------------------------------------------------------------


# Display the graph as a Mermaid diagram within Jupyter Notebook.
display(Image(graph.get_graph().draw_mermaid_png()))

# Also, save the graph visualization as a PNG file.
png_data = graph.get_graph().draw_mermaid_png()
with open("graph.png", "wb") as f:
    f.write(png_data)


# -------------------------------------------------------------------
# Begin the conversation with an initial agent output (agent jump-start)
# -------------------------------------------------------------------
print("Agent initiating conversation...\n")

state_data = {
    "messages": [],
    "step": FIRST_NODE
}
config = {"configurable": {"thread_id": str(uuid.uuid4())}}

# Perform an initial call to the state machine.
output_iter = graph.stream(state_data, config=config, stream_mode="updates")
last_output = None
for i, last_output in enumerate(output_iter):
    last_message = next(iter(last_output.values()))["messages"][-1]
    d = parse_output(last_message)
    print(f"AI: {d['response']}")


# -------------------------------------------------------------------
# Begin a simulated interactive conversation loop.
# -------------------------------------------------------------------
# Cached responses for non-interactive testing.

# cached_human_responses = ["hi!", "rag prompt", "1 rag, 2 none, 3 no, 4 no", "red", "q"]
# cached_response_index = 0
# Generate a unique thread ID for the conversation configuration.
config = {"configurable": {"thread_id": str(uuid.uuid4())}}

# state_data = {
#     "messages": [],
#     "step": 150
# }

# Infinite loop for conversation until user types 'q' or 'Q' to quit.
while True:
    
    # try:
    # Get user input from the terminal.
    user = input("User (q/Q to quit): ")
    # except:
    #     # If input fails (e.g., non-interactive environment), use cached responses.
    #     user = cached_human_responses[cached_response_index]
    #     cached_response_index += 1
    # print(f"User (q/Q to quit): {user}")
    # Exit the loop if the user wants to quit.
    if user in {"q", "Q"}:
        print("AI: Byebye")
        break
    output = None
    

    # Add the user's message to the conversation
    state_data["messages"].append(HumanMessage(content=user))

    # Now run the state machine in streaming mode
    output_iter = graph.stream(state_data, config=config, stream_mode="updates")
    
    # Keep track of the final output from this turn
    last_output = None
    for i, last_output in enumerate(output_iter):

    # Stream the conversation through the state graph.
    # for output in graph.stream(
        # {"messages": [HumanMessage(content=user)]}, config=config, stream_mode="updates"
    # ):
        print(f'\niteration: {i}')
        # Extract the latest message from the streamed output.
        last_message = next(iter(last_output.values()))["messages"][-1]
        # Pretty-print the last message.
        # last_message.pretty_print()

        d = parse_output(last_message)
        
        print(f"response:   {d['response']}")
        print(f"status:     {d['status']}")
        print(f"med hx:     {d['medical_history']}")
        

    # If a prompt is generated, indicate completion.
    if last_output and "prompt" in last_output:
        print("Done!")
