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

from .tools import flip_a_coin, list_environment_variables, roll_die

root_agent = Agent(
    model="gemini-2.0-flash",
    name="simple_tools_agent",
    description="A helpful AI assistant. You also can flip a coin, roll a dynamically sided die, or list environment variables with your tools.",
    instruction="""

        Be polite and answer all users' questions.
        
        You have access to three tools:
            1. `flip_a_coin`: Use this tool to flip a traditional 2 sided coin, with heads and tails.
            2. `roll_die`: Use this tool to roll a die based on how many sides of the die the user provides you.
            3. `list_environment_variables`: Use this tool to list all currently set environment variables.
    """,
    tools=[flip_a_coin, roll_die, list_environment_variables],
)
