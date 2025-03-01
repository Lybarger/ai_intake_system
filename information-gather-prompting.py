import getpass
import os
from typing import List
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from typing import Literal
from langgraph.graph import END  # Constant to indicate end of conversation
from langgraph.checkpoint.memory import MemorySaver  # For saving state checkpoints
from langgraph.graph import StateGraph, START  # StateGraph for workflow management, START constant
from langgraph.graph.message import add_messages  # Annotation for adding messages to state
from typing import Annotated
from typing_extensions import TypedDict
import uuid

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
# Define a template for gathering prompt instructions from a user.
# -------------------------------------------------------------------
template = """Your job is to get information from a user about what type of prompt template they want to create.

Engage in multiturn dialogue to identify each of the following. Ask each of these questions sequentially, one per conversational turn.

1. What the objective of the prompt is?
2. What variables will be passed into the prompt template?
3. What are the constraints for what the output should NOT do?
4. What are requirements that the output MUST adhere to?

If you are not able to discern this info, ask them to clarify! Do not attempt to wildly guess.

After you are able to discern all the information, call the relevant tool.


"""

# Prepend the system message (with the template) to the conversation messages.
def get_messages_info(messages):
    return [SystemMessage(content=template)] + messages

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
def info_chain(state):
    # Prepend the template instruction to the current state's messages.
    messages = get_messages_info(state["messages"])
    # Invoke the LLM (with the bound tool) using the modified messages.
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
    # If the last message is an AIMessage that contains a tool call, transition to "add_tool_message".
    if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
        return "add_tool_message"
    # If the last message is not from a human, consider the conversation ended.
    elif not isinstance(messages[-1], HumanMessage):
        return END
    # Otherwise, remain in the "info" state.
    return "info"

# -------------------------------------------------------------------
# Define a typed dictionary for the conversation state.
# -------------------------------------------------------------------
class State(TypedDict):
    messages: Annotated[list, add_messages]

# -------------------------------------------------------------------
# Initialize memory for checkpointing and create the workflow state graph.
# -------------------------------------------------------------------
memory = MemorySaver()
workflow = StateGraph(State)
workflow.add_node("info", info_chain)       # Node for gathering prompt information.
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
workflow.add_conditional_edges("info", get_state, ["add_tool_message", "info", END])
workflow.add_edge("add_tool_message", "prompt")
workflow.add_edge("prompt", END)
workflow.add_edge(START, "info")
# Compile the workflow into a graph with memory checkpointing.
graph = workflow.compile(checkpointer=memory)

# -------------------------------------------------------------------
# Render and save the state graph visualization.
# -------------------------------------------------------------------
from IPython.display import Image, display

# Display the graph as a Mermaid diagram within Jupyter Notebook.
display(Image(graph.get_graph().draw_mermaid_png()))

# Also, save the graph visualization as a PNG file.
png_data = graph.get_graph().draw_mermaid_png()
with open("graph.png", "wb") as f:
    f.write(png_data)

# -------------------------------------------------------------------
# Begin a simulated interactive conversation loop.
# -------------------------------------------------------------------
# Cached responses for non-interactive testing.
cached_human_responses = ["hi!", "rag prompt", "1 rag, 2 none, 3 no, 4 no", "red", "q"]
cached_response_index = 0
# Generate a unique thread ID for the conversation configuration.
config = {"configurable": {"thread_id": str(uuid.uuid4())}}

state_data = {
    "messages": [],
    "stage": 150
}

# Infinite loop for conversation until user types 'q' or 'Q' to quit.
while True:
    
    try:
        # Get user input from the terminal.
        user = input("User (q/Q to quit): ")
    except:
        # If input fails (e.g., non-interactive environment), use cached responses.
        user = cached_human_responses[cached_response_index]
        cached_response_index += 1
    print(f"User (q/Q to quit): {user}")
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
        last_message.pretty_print()

    # If a prompt is generated, indicate completion.
    if last_output and "prompt" in last_output:
        print("Done!")
