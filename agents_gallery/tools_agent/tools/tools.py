
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
import uuid

from google.cloud import secretmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def flip_a_coin() -> str:
    """Simulates flipping a coin, returning either "Heads" or "Tails".

    Returns:
        A string indicating the the result of the coin flip.
        Example: 'Heads'
    """
    # Placeholder implementation - replace with actual video call initiation
    logger.info("Flipping a coin...")

    # simulate flipping a coin with equal probability of heads or tails
    result = "Heads" if uuid.uuid4().int % 2 == 0 else "Tails"
    return result


def roll_die(die_sides: int) -> str:
    """Simulates rolling a single die, the total number of sides is provided as an input to the function.

    Returns:
        A string indicating the the result of the roll of a die.
        Example: '8'
    """
    # Placeholder implementation - replace with actual video call initiation
    logger.info("rolling a die...")

    # simulate rolling a die based on the number of sides
    result = str(uuid.uuid4().int % die_sides)
    return result

def list_environment_variables() -> dict[str, str]:
    """Lists specified environment variables: 'variable1' and 'variable2'.

    Returns:
        A dictionary where keys are the specified environment variable names
        and values are their corresponding values. If a variable is not set,
        it will not be included in the dictionary.
    """
    logger.info("Listing specific environment variables: variable1, variable2...")
    specified_vars = ["VARIABLE1"
                      ,"VARIABLE2"]
    env_vars = {}
    for var_name in specified_vars:
        var_value = os.environ.get(var_name)
        if var_value is not None:
            env_vars[var_name] = var_value
    return env_vars


def get_secret_from_secret_manager(
    project_id: str = "csaw-workshop1",
    secret_id: str = "sample-secret-for-adk",
    version_id: str = "latest",
) -> str:
    """Retrieves a secret value from Google Cloud Secret Manager.

    Args:
        project_id: The Google Cloud project ID. Defaults to "csaw-workshop1".
        secret_id: The ID of the secret to access. Defaults to
            "sample-secret-for-adk".
        version_id: The version of the secret to access. Defaults to "latest".

    Returns:
        A formatted string with the secret ID and its value on success, or an
        error message if it fails.
        Example: 'secret id: my-secret\\nsecret value: my-secret-value'
    """
    logger.info(
        "Attempting to access secret '%s' (version: %s) in project '%s'...",
        secret_id,
        version_id,
        project_id,
    )
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")
        return f"secret id: {secret_id}\nsecret value: {secret_value}"
    except Exception as e:
        error_message = f"Failed to access secret '{secret_id}' in project '{project_id}'. Error: {e}"
        logger.error(error_message)
        return error_message
