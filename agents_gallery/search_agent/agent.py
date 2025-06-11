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

from google.adk.agents import Agent
from google.adk.tools import google_search

# Must be named root_agent (for root agent, subagents can be different).
root_agent = Agent(
    model="gemini-2.0-flash",
    name="search_agent",
    description="A helpful AI assistant that can conduct a Google Search for you.",
    instruction="""
        Be polite and answer all users' questions.
    """,
    tools=[google_search],
)
