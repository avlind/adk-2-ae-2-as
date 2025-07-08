
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

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.tools import ToolContext

context = {
    "current_round_number": 1,
}


def debate_status(callback_context: CallbackContext):
    current_round = callback_context.state.get("current_round_number", 0)
    print(f"END ROUND: {current_round}")
    callback_context.state["current_round_number"] = current_round + 1


def stop(reason: str, tool_context: ToolContext):
    """Indicate that the debate is over."""
    tool_context.actions.escalate = True

    return reason


affirmative_agent = Agent(
    name="affirmative_agent",
    model="gemini-2.0-flash-001",
    instruction="""
      You are the first speaker from the affirmative team in a debate.
      You are supportive to the topic.
      You will be given a topic to debate.
      Your job is to make a speech supporting the affirmative position.
      Your speech must be concise, less than 50 words.
      In addition to your statement, you can also ask a question to the
      other team.
      If there's a question to you, you will answer it.
      Prefix your speech with [affirmative_agent].
""",
)

opposition_agent = Agent(
    name="opposition_agent",
    model="gemini-2.0-flash-001",
    instruction="""
      You are the first speaker from the opposition team in a debate.
      You are against to the topic.
      You will be given a topic to debate.
      Your job is to make a speech supporting the opposition position.
      Your speech must be concise, less than 50 words.
      In addition to your statement, you can also ask a question to the
      other team.
      If there's a question to you, you will answer it.
      Prefix your speech with [opposition_agent].
""",
)

judge_agent = Agent(
    name="judge_agent",
    model="gemini-2.0-flash-001",
    instruction="""
    You serve as the judge of a debate.
    Your job is to moderate the debate, ensuring that both sides have a fair
    chance to present their arguments.

    If any of the participants are rude or offensive, you reply with
    [warning], followed by a warning message.

    If you think the debate doesn't have a clear outcome or enough information,
    you reply with [continue] to let the debate continue.

    If you think the outcome of the debate is clear, you must to the 2 steps:
    1. State the winner and the reason with '[winner] <winner>\n<reason>'.
    2. Then call exit_loop function.

""",
    tools=[stop],
)

loop_agent = LoopAgent(
    name="debate_team",
    sub_agents=[affirmative_agent, opposition_agent, judge_agent],
)

root_agent = Agent(
    name="debate_host",
    model="gemini-2.0-flash-001",
    instruction=""""
        You are a debate host, your job is to extract from the user a debate topic for which the debate_team will then argure and judge a winner.
        If the user asks you can provide a few options that may be relevant.
        If a user decided to go with one of your suggestions, you must get confirmation before transfering to the debate_team."
        """,
    sub_agents=[loop_agent],
)
