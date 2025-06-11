import json
import logging  # Use logging instead of print for status/errors
import os
from typing import Any, Dict, List, Optional, Tuple  # Added for type hinting

import google.auth
import google.auth.transport.requests
import requests
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

# --- Constants ---
# Default locations - read from environment or use fallback
DEFAULT_LOCATIONS_FALLBACK = "global,us"
AGENTSPACE_DEFAULT_LOCATIONS = os.getenv("AGENTSPACE_LOCATIONS", DEFAULT_LOCATIONS_FALLBACK)
# API Scopes needed
API_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

class DiscoveryEngineError(Exception):
    """Custom exception for errors during Discovery Engine operations."""
    pass

def _get_auth_details(project_id_override: Optional[str] = None) -> Tuple[google.auth.credentials.Credentials, Optional[str], str]:
    """Gets application default credentials, token, and effective project ID.

    Args:
        project_id_override: An optional project ID to use instead of ADC's default.

    Returns:
        A tuple containing credentials, access token, and effective project ID.

    Raises:
        DiscoveryEngineError: If authentication fails or project ID cannot be determined.
    """
    try:
        credentials, project_id_from_adc = google.auth.default(scopes=API_SCOPES)
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        effective_project_id = project_id_override or project_id_from_adc
        if not effective_project_id:
             raise DiscoveryEngineError("Project ID not found. Please provide project_id or run 'gcloud config set project <your-project-id>'")

        logging.info(f"Using Project ID for lookup: {effective_project_id}")
        # Ensure token exists before returning
        if not credentials.token:
            raise DiscoveryEngineError("Failed to obtain access token after refreshing credentials.")
        return credentials, credentials.token, effective_project_id
    except google.auth.exceptions.DefaultCredentialsError as e:
        logging.error(f"Authentication error: {e}. Ensure ADC setup ('gcloud auth application-default login').")
        raise DiscoveryEngineError(f"Authentication error: {e}") from e
    except Exception as e:
        logging.error(f"An unexpected error occurred during authentication: {e}")
        raise DiscoveryEngineError(f"An unexpected error occurred during authentication: {e}") from e

def _get_project_number(project_id: str, credentials: google.auth.credentials.Credentials) -> str:
    """Looks up the project number using the Cloud Resource Manager API.

    Args:
        project_id: The project ID string.
        credentials: The authenticated Google credentials.

    Returns:
        The project number as a string.

    Raises:
        DiscoveryEngineError: If the project number cannot be retrieved.
    """
    try:
        service = build('cloudresourcemanager', 'v1', credentials=credentials)
        project = service.projects().get(projectId=project_id).execute()
        project_number = project.get('projectNumber')
        if project_number:
            logging.info(f"Successfully looked up Project Number for '{project_id}': {project_number}")
            return project_number
        else:
            logging.error(f"Could not find project number for project ID '{project_id}'. Response: {project}")
            raise DiscoveryEngineError(f"Could not find project number for project ID '{project_id}'")
    except HttpError as e:
        logging.error(f"Error calling Cloud Resource Manager API for project '{project_id}': {e}")
        if e.resp.status == 403:
            logging.error("Ensure the Cloud Resource Manager API is enabled and credentials have permissions (e.g., roles/cloudresourcemanager.projectViewer).")
        raise DiscoveryEngineError(f"Cloud Resource Manager API error for project '{project_id}': {e}") from e
    except Exception as e:
        logging.error(f"An unexpected error occurred during project number lookup: {e}")
        raise DiscoveryEngineError(f"An unexpected error occurred during project number lookup: {e}") from e


def _fetch_matching_engines(project_number: str, locations: List[str] | str, access_token: str) -> List[Dict[str, Any]]:
    """Fetches engines via REST and returns details for those with requiredSubscriptionTier.

    Args:
        project_number: The numeric ID (as a string) of the Google Cloud project.
        locations: A list of strings or a comma-separated string of Google Cloud locations.
        access_token: The OAuth2 access token for authorization.

    Returns:
        A list of dictionaries, each containing 'engine_id', 'location', and 'tier'
        for engines that have requiredSubscriptionTier set.
    """
    matching_engines_details = []

    if not access_token:
        logging.error("Missing access token for fetching engines.")
        return []
    if not project_number:
        logging.error("Missing project number for fetching engines.")
        return []

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_number # Use project number here as per API docs
    }

    # Ensure locations is a list of strings
    if isinstance(locations, list):
        # Ensure all elements are strings and stripped of whitespace, ignore empty ones
        location_list = [str(loc).strip() for loc in locations if str(loc).strip()]
    elif isinstance(locations, str): # Keep handling for string input just in case
        location_list = [loc.strip() for loc in locations.split(",") if loc.strip()]
    else:
        logging.warning("Invalid 'locations' type provided. Expected list or comma-separated string.")
        return [] # Return empty list if locations format is wrong

    for location in location_list:
        logging.info(f"Checking location via REST: {location} (Project Number: {project_number})")
        api_host = (
            f"{location}-discoveryengine.googleapis.com"
            if location != "global" else "discoveryengine.googleapis.com"
        )
        # Using v1beta as determined previously
        api_endpoint = f"https://{api_host}/v1beta/projects/{project_number}/locations/{location}/collections/default_collection/engines"

        try:
            logging.debug(f"Calling API: {api_endpoint}")
            response = requests.get(api_endpoint, headers=headers, timeout=30) # Added timeout
            response.raise_for_status()

            data = response.json()
            engines_in_response = data.get("engines", [])

            if not engines_in_response:
                logging.info(f"No engines found in {location} under default_collection.")
                continue

            logging.info(f"Found {len(engines_in_response)} engine(s) in {location}. Checking for 'subscription_tier_search_and_assistant' tier...")
            engines_matched_in_location = 0
            for engine in engines_in_response:
                search_config = engine.get("searchEngineConfig")
                retrieved_tier = search_config.get("requiredSubscriptionTier") if search_config else None

                # Check if the key exists AND if its value matches the desired tier (case-insensitive)
                if retrieved_tier and retrieved_tier.lower() == "subscription_tier_search_and_assistant":
                        engines_matched_in_location += 1
                        engine_id = engine.get("name", "N/A").split('/')[-1]
                        tier = search_config.get("requiredSubscriptionTier") # We know it exists and matches
                        matching_engines_details.append({
                            "engine_id": engine_id,
                            "location": location,
                            "tier": tier
                        })
                        logging.debug(f"  Match found - Engine ID: {engine_id}, Location: {location}, Tier: {tier}")
                elif retrieved_tier: # Log if tier exists but doesn't match
                    # Log engines that have the tier key but not the right value (optional, but helpful for debugging)
                    logging.debug(f"  Skipping engine {engine.get('name', 'N/A').split('/')[-1]} in {location} - Tier is '{retrieved_tier}' (not 'subscription_tier_search_and_assistant').")


            if engines_matched_in_location == 0:
                logging.info(f"No engines in {location} matched the requiredSubscriptionTier criteria.")

        except requests.exceptions.Timeout:
             logging.warning(f"Timeout calling API for location {location}: {api_endpoint}")
        except requests.exceptions.RequestException as e:
             logging.error(f"Error calling API for location {location}: {e}")
             if isinstance(e, requests.exceptions.HTTPError):
                 try:
                     logging.error(f"Response Body: {e.response.text}")
                 except Exception:
                     logging.error("Could not read error response body.")
             # Continue to the next location if one fails
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON response for location {location}.")
        except Exception as e:
             logging.error(f"An unexpected error occurred processing location {location}: {e}")
             # Optionally re-raise or handle more specifically

    return matching_engines_details


def get_agentspace_apps_from_projectid(project_id: str, locations: List[str] | str = AGENTSPACE_DEFAULT_LOCATIONS) -> List[Dict[str, Any]]:
    """
    Retrieves Discovery Engine apps (engines) from a specified project and locations
    that have the 'requiredSubscriptionTier' attribute set.

    Args:
        project_id: The Google Cloud Project ID string.
        locations: A list of strings or a comma-separated string of Google Cloud locations
                   (e.g., ["global", "us"] or "global,us").
                   Defaults to the value of AGENTSPACE_LOCATIONS from .env or "global,us".

    Returns:
        A list of dictionaries. Each dictionary contains:
        - 'engine_id': The ID of the engine.
        - 'location': The location of the engine.
        - 'tier': The value of the 'requiredSubscriptionTier'.
        Returns an empty list if no matching engines are found or an error occurs.

    Raises:
        DiscoveryEngineError: If authentication or project number lookup fails.
    """
    try:
        # 1. Authenticate and get project ID if needed (though project_id is required here)
        credentials, access_token, _ = _get_auth_details(project_id_override=project_id)
        if not access_token: # Added check
            raise DiscoveryEngineError("Failed to obtain access token during authentication.")

        # 2. Get Project Number
        project_number = _get_project_number(project_id, credentials)

        # 3. Fetch matching engines
        matching_engines = _fetch_matching_engines(project_number, locations, access_token)

        logging.info(f"Found {len(matching_engines)} engine(s) with tier 'subscription_tier_search_and_assistant'.")
        return matching_engines

    except DiscoveryEngineError as e:
        # Log the error already raised by helper functions
        logging.error(f"Failed to get agentspace apps: {e}")
        return [] # Return empty list on handled errors
    except Exception as e:
        # Catch any other unexpected errors
        logging.exception(f"An unexpected critical error occurred in get_agentspace_apps_from_projectid: {e}")
        return []
