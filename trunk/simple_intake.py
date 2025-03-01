import os
from langchain.llms import OpenAI
from langchain.chains import ConversationChain
from langchain.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory
# Import LangGraph components (adjust the import path if necessary)
from langgraph.graph import Graph, Node

# Determine the absolute path to the API key file located two directories above
script_dir = os.path.dirname(os.path.abspath(__file__))
api_key_path = os.path.join(script_dir, '..', '..', 'OPENAI_API_KEY')

# Read the API key from the file and set it as an environment variable
with open(api_key_path, 'r') as key_file:
    api_key = key_file.read().strip()
os.environ["OPENAI_API_KEY"] = api_key


# Instantiate the LLM (using GPT-4 here; adjust parameters as needed)
llm = OpenAI(model_name="gpt-4o", temperature=0.7)

def create_conversation_node(name: str, prompt_text: str) -> Node:
    """
    Creates a conversation node that uses a ConversationChain with memory.
    Each node represents a distinct phase of the medical intake.
    """
    # Use a conversation buffer to maintain multi-turn dialogue context
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
    # Define a prompt template that includes the chat history and the current patient input
    prompt = PromptTemplate(
        input_variables=["chat_history", "patient_input"],
        template=prompt_text
    )
    # Create a conversation chain for this phase
    conversation_chain = ConversationChain(llm=llm, prompt=prompt, memory=memory)
    # Create and return a LangGraph Node encapsulating the chain
    node = Node(name=name, chain=conversation_chain)
    return node

# Define prompt templates for each conversation phase.
# Note: Including "chat_history" allows the agent to refer back to earlier dialogue in the phase.
demographics_prompt = (
    "The following is a conversation between an agent and a patient.\n"
    "Agent: Please provide your basic demographic information (e.g., age, gender, etc.).\n"
    "Patient: {patient_input}\n"
    "Chat history: {chat_history}\n"
    "Agent:"
)

medications_prompt = (
    "The following is a conversation between an agent and a patient.\n"
    "Agent: Please list any current medications you are taking, including dosage and frequency.\n"
    "Patient: {patient_input}\n"
    "Chat history: {chat_history}\n"
    "Agent:"
)

diagnoses_prompt = (
    "The following is a conversation between an agent and a patient.\n"
    "Agent: Please describe any past or current diagnoses you have received.\n"
    "Patient: {patient_input}\n"
    "Chat history: {chat_history}\n"
    "Agent:"
)

# Create conversation nodes for each phase.
demographics_node = create_conversation_node("demographics", demographics_prompt)
medications_node = create_conversation_node("medications", medications_prompt)
diagnoses_node = create_conversation_node("diagnoses", diagnoses_prompt)

# Instantiate a LangGraph and add the nodes.
graph = Graph()
graph.add_node(demographics_node)
graph.add_node(medications_node)
graph.add_node(diagnoses_node)

# Connect the nodes sequentially.
# In this simplified example, we assign a "next_node" attribute to guide sequential execution.
demographics_node.next_node = medications_node
medications_node.next_node = diagnoses_node

def run_medical_intake():
    """
    Simulates the multi-phase conversation by iterating through the nodes.
    At each phase, the system collects patient input and produces an agent response.
    """
    current_node = demographics_node
    while current_node:
        # Collect patient input for the current phase.
        patient_input = input(f"[{current_node.name.upper()}] Your input: ")
        # Execute the conversation chain for the current node.
        response = current_node.chain.run({"patient_input": patient_input})
        print(f"Agent: {response}\n")
        # Transition to the next phase (node), if available.
        current_node = getattr(current_node, "next_node", None)

if __name__ == "__main__":
    run_medical_intake()
