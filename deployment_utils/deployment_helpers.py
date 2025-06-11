import os
import sys


def load_env_variables(relative_path: str) -> dict[str, str]:
    """
    Opens a .env file specified by a relative path, parses it,
    and returns a dictionary of the key-value pairs found within,
    excluding certain reserved environment variables.

    This function does not modify os.environ and only includes variables
    explicitly defined in the .env file, filtering out reserved ones.

    Args:
        relative_path: The relative path to the .env file from the directory
                       containing this script (deployment_helpers.py).

    Returns:
        A dictionary containing the environment variables from the .env file,
        excluding reserved keys. Returns an empty dictionary if the file does
        not exist, cannot be read, is empty, or contains no valid entries.
    """
    """
    Opens a .env file specified by a relative path, parses it,
    and returns a dictionary of the key-value pairs found within.
    This function does not modify os.environ and only includes variables
    explicitly defined in the .env file.

    Args:
        relative_path: The relative path to the .env file from the directory
                       containing this script (deployment_helpers.py).

    Returns:
        A dictionary containing the environment variables from the .env file.
        Returns an empty dictionary if the file does not exist, cannot be read,
        is empty, or contains no valid entries.
    """
    # Define the list of environment variables to skip
    RESERVED_ENV_VARS = {
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_QUOTA_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "PORT",
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
    }
    # Define the prefix for environment variables to skip
    RESERVED_PREFIX = "GOOGLE_CLOUD_AGENT_ENGINE"

    # Determine the absolute path to this script (deployment_helpers.py)
    # to correctly resolve the relative_path for the .env file.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(base_dir, relative_path)

    env_vars: dict[str, str] = {}

    if not os.path.exists(dotenv_path):
        # print(f"Info: .env file not found at {dotenv_path}", file=sys.stderr)
        return env_vars

    try:
        with open(dotenv_path, 'r', encoding='utf-8') as f:
            for line_content in f:
                line = line_content.strip()

                if not line or line.startswith('#'): # Skip empty lines and comments
                    continue

                if '=' not in line: # Skip lines without an '=' separator
                    continue

                key, value = line.split('=', 1)
                key = key.strip()
                # Handle 'export' prefix (e.g., "export KEY=VALUE")
                if key.startswith("export "):
                    key = key.split(" ", 1)[1].strip()

                # Skip reserved environment variables
                if key in RESERVED_ENV_VARS or key.startswith(RESERVED_PREFIX):
                    # print(f"Skipping reserved environment variable: {key}", file=sys.stderr) # Optional: for debugging
                    continue

                # Strip inline comments from the value part first
                if '#' in value:
                    value = value.split('#', 1)[0]

                value = value.strip() # Strip whitespace from the (potentially comment-stripped) value

                # Remove surrounding quotes (single or double) from the value
                if len(value) > 1 and ((value.startswith('"') and value.endswith('"')) or \
                                       (value.startswith("'") and value.endswith("'"))):
                    value = value[1:-1]

                if key: # Ensure key is not empty
                    env_vars[key] = value
    except IOError as e:
        print(f"Warning: Could not read .env file at {dotenv_path}. Error: {e}", file=sys.stderr)
        return {} # Return empty if file read fails

    return env_vars
