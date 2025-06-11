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


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    """Converts a value from one unit to another.
    Args:
        value: The numerical value to convert.
        from_unit: The unit of the input value (e.g., 'miles', 'celsius').
        to_unit: The desired unit for the output (e.g., 'kilometers', 'fahrenheit').
    Returns:
        The converted value, or None if the conversion is not supported.
    """
    if from_unit.lower() == "miles" and to_unit.lower() == "kilometers":
        return value * 1.60934
    elif from_unit.lower() == "kilometers" and to_unit.lower() == "miles":
        return value / 1.60934
    elif from_unit.lower() == "celsius" and to_unit.lower() == "fahrenheit":
        return (value * 9 / 5) + 32
    elif from_unit.lower() == "fahrenheit" and to_unit.lower() == "celsius":
        return (value - 32) * 5 / 9
    elif from_unit.lower() == "miles" and to_unit.lower() == "millimeters":
        return value * 1609340
    elif from_unit.lower() == "millimeters" and to_unit.lower() == "miles":
        return value / 1609340
    else:
        return None


# Must be named root_agent
root_agent = Agent(
    model="gemini-2.0-flash",
    name="unit_converter_agent",
    description="A helpful AI assistant that can convert between different units.",
    instruction="""
        Be polite and answer all users' questions pretending to be looking up unit conversions.

        The user must provide a numerical value, the original unit, and the target unit.
        For example: "Convert 10 miles to kilometers" or "What is 25 degrees Celsius in Fahrenheit?".

        You have access to the tool `convert_units`: Use this tool to perform the unit conversion.
    """,
    tools=[convert_units],
)
