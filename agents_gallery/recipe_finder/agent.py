#  Copyright (C) 2025 Google LLC
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools import VertexAiSearchTool

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Load environment specific entries from env file
load_dotenv()
RECIPE_DATASTORE: str = os.environ.get("RECIPE_DATASTORE")
MODEL_NAME: str = os.environ.get("MODEL_NAME")
INSTRUCTIONS ="""You are a helpful assistant specializing in looking up cooking recipes from a Vertex AI Search Datastore.
        Use the search tool to find relevant information before answering.
        If the answer isn't in the documents, say that you couldn't find the information."""

# # Initialize the Vertex AI Search tool
recipe_search_tool = VertexAiSearchTool(data_store_id=RECIPE_DATASTORE)
    
# Define Root Agent
root_agent = Agent(
    name="RootAgent",
    model=MODEL_NAME,
    description="Root Agent",
    instruction=INSTRUCTIONS,
    tools=[recipe_search_tool],
)
