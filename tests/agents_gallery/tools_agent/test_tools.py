
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

# Unit testing for the functions

from agents_gallery.tools_agent.tools import flip_a_coin, roll_die


def test_flip_a_coin_returns_heads_or_tails():
    """
    Test that flip_a_coin returns either "Heads" or "Tails".
    """
    result = flip_a_coin()
    assert result in ["Heads", "Tails"]


def test_roll_die_returns_number_within_range():
    """
    Test that roll_die returns a number within the expected range.
    """
    die_sides = 6
    result = roll_die(die_sides)
    assert result.isdigit()
    assert 0 <= int(result) < die_sides

    die_sides = 10
    result = roll_die(die_sides)
    assert result.isdigit()
    assert 0 <= int(result) < die_sides

    die_sides = 1
    result = roll_die(die_sides)
    assert result.isdigit()
    assert 0 <= int(result) < die_sides

    die_sides = 2
    result = roll_die(die_sides)
    assert result.isdigit()
    assert 0 <= int(result) < die_sides
