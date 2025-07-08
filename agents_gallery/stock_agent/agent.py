
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

import yfinance as yf
from google.adk.agents import Agent


def get_stock_price(symbol: str) -> dict:
    """Returns the current (delayed) stock price given the symbol.
    Args:
      symbol: GOOG, AAPL, MSFT, etc.
    """
    dat = yf.Ticker(symbol)
    return dat.info


# Must be named root_agent (for root agent, sub-agents can be different).
root_agent = Agent(
    model="gemini-2.0-flash",
    name="stock_agent",
    description="A helpful AI assistant that can lookup latest (20 minute delayed) stock price.",
    instruction="""
        Be polite and answer all users' questions pretending to looking up stock prices.
        
        User must provide a stock ticker, not the company name.
        
        You have access to tools: `get_stock_price`: Use this tool to get the current (delayed) stock price.
    """,
    tools=[get_stock_price],
)
