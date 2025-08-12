
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import asyncio
import copy
import importlib
import json
import logging
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import google.auth
import google.auth.transport.requests
import requests
import vertexai
from google.api_core import exceptions as google_exceptions
from google.cloud import resourcemanager_v3
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from nicegui import ui

logger = logging.getLogger("WebUIManagerActivity")

# --- Constants ---
_BASE_REQUIREMENTS = [
    "python-dotenv",
    "requests",
    "google-cloud-resource-manager",
]
AS_AUTH_API_BASE_URL = "https://discoveryengine.googleapis.com/v1alpha"
AS_AUTH_DEFAULT_LOCATION = "global"
DEFAULT_LOCATIONS_FALLBACK = "global,us"
AGENTSPACE_DEFAULT_LOCATIONS = os.getenv("AGENTSPACE_LOCATIONS", DEFAULT_LOCATIONS_FALLBACK)
API_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# --- Custom Exceptions ---
class DiscoveryEngineError(Exception):
    """Custom exception for errors during Discovery Engine operations."""
    pass

# --- Helper Functions ---

def init_vertex_ai(
    project_id: str, location: str, staging_bucket: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    try:
        bucket_info = (
            f"(Bucket: gs://{staging_bucket})"
            if staging_bucket
            else "(No bucket specified)"
        )
        logger.info(
            f"Initializing Vertex AI SDK for {project_id}/{location} {bucket_info}..."
        )
        init_kwargs = {"project": project_id, "location": location}
        if staging_bucket:
            init_kwargs["staging_bucket"] = f"gs://{staging_bucket}"
        vertexai.init(**init_kwargs)
        logger.info("Vertex AI initialized successfully.")
        return True, None
    except google_exceptions.NotFound:
        bucket_error = (
            f"or Bucket '{staging_bucket}' invalid/inaccessible"
            if staging_bucket
            else ""
        )
        msg = f"Error: Project '{project_id}' or Location '{location}' not found, or Vertex AI API not enabled, {bucket_error}."
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Error initializing Vertex AI SDK: {e}"
        logger.error(msg)
        return False, msg

def get_project_number_sync(project_id: str) -> Optional[str]:
    try:
        client = resourcemanager_v3.ProjectsClient()
        request = resourcemanager_v3.GetProjectRequest(name=f"projects/{project_id}")
        project = client.get_project(request=request)
        return project.name.split("/")[-1]
    except Exception as e:
        logger.error(f"Error getting project number for '{project_id}': {e}")
        return None

async def get_project_number(project_id: str) -> Optional[str]:
    if not project_id:
        return None
    return await asyncio.to_thread(get_project_number_sync, project_id)

async def get_agent_root_nicegui(
    agent_config: dict,
) -> Tuple[Optional[Any], dict[str, str], Optional[str]]:
    module_path = agent_config.get("module_path", "")
    var_name = agent_config.get("root_variable", "")

    if not all([module_path, var_name]):
        error_msg = (
            "Agent configuration is missing 'module_path' or 'root_variable'.\n"
            f"Config provided: {agent_config}"
        )
        logger.error(f"Agent Import Error: {error_msg}")
        return None, {}, error_msg

    def _blocking_import_and_load():
        loaded_env_vars: dict[str, str] = {}
        env_file_relative_to_deploy_script = agent_config.get("local_env_file")
        if env_file_relative_to_deploy_script:
            env_file_relative_to_helpers = os.path.join(
                "..", env_file_relative_to_deploy_script.lstrip("./")
            )
            loaded_vars = load_env_variables(env_file_relative_to_helpers)
            if loaded_vars:
                logger.info(
                    f"Updating deployment script's environment with {len(loaded_vars)} variables from agent's .env file."
                )
                os.environ.update(loaded_vars)
                loaded_env_vars = loaded_vars

        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        parent_dir = os.path.dirname(script_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)

        agent_module = importlib.import_module(module_path)
        root_agent = getattr(agent_module, var_name)
        return root_agent, loaded_env_vars

    try:
        print(f"Importing '{var_name}' from module '{module_path}'...")

        root_agent, agent_loaded_env_vars = await asyncio.to_thread(
            _blocking_import_and_load
        )

        logger.info(
            f"Successfully imported root agent '{var_name}' from '{module_path}'."
        )
        return root_agent, agent_loaded_env_vars, None

    except ImportError:
        tb_str = traceback.format_exc()
        error_msg = (
            f"Failed to import module '{module_path}'.\n"
            "Check 'module_path' in deployment_configs.py and ensure the module exists.\n\n"
            f"Traceback: {tb_str}"
        )
        logger.error(f"Agent Import Error: {error_msg}")
        return None, {}, error_msg
    except AttributeError:
        error_msg = (
            f"Module '{module_path}' does not have an attribute named '{var_name}'.\n"
            "Check 'root_variable' in deployment_configs.py."
        )
        logger.error(f"Agent Import Error: {error_msg}")
        return None, {}, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred during agent import: {e}\n{traceback.format_exc()}"
        logger.error(f"Agent Import Error: {error_msg}")
        return None, {}, error_msg

async def update_timer(
    start_time: float,
    timer_label: ui.label,
    stop_event: asyncio.Event,
    status_area: ui.element,
):
    while not stop_event.is_set():
        elapsed_seconds = time.monotonic() - start_time
        minutes, seconds = divmod(int(elapsed_seconds), 60)
        time_str = f"{minutes:02d}:{seconds:02d}"
        try:
            with status_area:
                timer_label.set_text(f"Elapsed Time: {time_str}")
        except Exception as e:
            logger.warning(f"Error updating timer UI: {e}")
            break
        await asyncio.sleep(1)

def get_access_token_and_credentials_sync_webui() -> (
    tuple[str | None, google.auth.credentials.Credentials | None, str | None]
):
    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            return None, None, "Failed to refresh token from ADC."
        return credentials.token, credentials, None
    except Exception as e:
        return None, None, f"Error getting access token and credentials: {e}"

async def get_access_token_and_credentials_async_webui() -> (
    tuple[str | None, google.auth.credentials.Credentials | None, str | None]
):
    return await asyncio.to_thread(get_access_token_and_credentials_sync_webui)

def create_authorization_sync_webui(
    target_project_id: str,
    target_project_number: str,
    auth_id: str,
    client_id: str,
    client_secret: str,
    auth_uri: str,
    token_uri: str,
    access_token: str,
) -> tuple[bool, str]:
    url = f"{AS_AUTH_API_BASE_URL}/projects/{target_project_number}/locations/{AS_AUTH_DEFAULT_LOCATION}/authorizations?authorizationId={auth_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": target_project_id,
    }
    payload = {
        "name": f"projects/{target_project_number}/locations/{AS_AUTH_DEFAULT_LOCATION}/authorizations/{auth_id}",
        "serverSideOauth2": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "authorizationUri": auth_uri,
            "tokenUri": token_uri,
        },
    }
    try:
        logger.info(
            f"Attempting to create authorization: {auth_id} in project {target_project_id} (number: {target_project_number})"
        )
        logged_payload = copy.deepcopy(payload)
        if (
            "serverSideOauth2" in logged_payload
            and "clientSecret" in logged_payload["serverSideOauth2"]
        ):
            logged_payload["serverSideOauth2"]["clientSecret"] = "[redacted]"
        log_headers = {
            k: ("Bearer [token redacted]" if k == "Authorization" else v)
            for k, v in headers.items()
        }
        logger.info(
            f"CREATE_AUTHORIZATION_REQUEST:\nMethod: POST\nURL: {url}\nHeaders: {json.dumps(log_headers, indent=2)}\nPayload: {json.dumps(logged_payload, indent=2)}"
        )

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        response_json = response.json()
        logger.info(
            f"CREATE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}"
        )
        return (
            True,
            f"Successfully created authorization '{auth_id}'.\nResponse: {json.dumps(response_json, indent=2)}",
        )
    except requests.exceptions.RequestException as e:
        error_detail = (
            f"Status: {e.response.status_code}, Body: {e.response.text}"
            if e.response
            else str(e)
        )
        msg = f"API call to create authorization failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization creation: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

def delete_authorization_sync_webui(
    target_project_id: str,
    target_project_number: str,
    auth_id: str,
    access_token: str,
) -> tuple[bool, str]:
    url = f"{AS_AUTH_API_BASE_URL}/projects/{target_project_number}/locations/{AS_AUTH_DEFAULT_LOCATION}/authorizations/{auth_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": target_project_id,
    }
    try:
        logger.info(
            f"Attempting to delete authorization: {auth_id} in project {target_project_id} (number: {target_project_number})"
        )
        log_headers = {
            k: ("Bearer [token redacted]" if k == "Authorization" else v)
            for k, v in headers.items()
        }
        logger.info(
            f"DELETE_AUTHORIZATION_REQUEST:\nMethod: DELETE\nURL: {url}\nHeaders: {json.dumps(log_headers, indent=2)}"
        )

        response = requests.delete(url, headers=headers)
        response.raise_for_status()
        logger.info(
            f"DELETE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{response.text if response.text else '(empty body)'}"
        )
        return (
            True,
            f"Successfully deleted authorization '{auth_id}'. Status: {response.status_code}",
        )
    except requests.exceptions.RequestException as e:
        error_detail = (
            f"Status: {e.response.status_code}, Body: {e.response.text}"
            if e.response
            else str(e)
        )
        msg = f"API call to delete authorization failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization deletion: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg


def list_authorizations_sync_webui(
    target_project_id: str,
    target_project_number: str,
    access_token: str,
) -> tuple[bool, str | list]:
    url = f"{AS_AUTH_API_BASE_URL}/projects/{target_project_number}/locations/{AS_AUTH_DEFAULT_LOCATION}/authorizations"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": target_project_id,
    }
    try:
        logger.info(
            f"Attempting to list authorizations in project {target_project_id} (number: {target_project_number})"
        )
        log_headers = {
            k: ("Bearer [token redacted]" if k == "Authorization" else v)
            for k, v in headers.items()
        }
        logger.info(
            f"LIST_AUTHORIZATIONS_REQUEST:\nMethod: GET\nURL: {url}\nHeaders: {json.dumps(log_headers, indent=2)}"
        )

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response_json = response.json()
        logger.info(
            f"LIST_AUTHORIZATIONS_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}"
        )
        return True, response_json.get("authorizations", [])
    except requests.exceptions.RequestException as e:
        error_detail = (
            f"Status: {e.response.status_code}, Body: {e.response.text}"
            if e.response
            else str(e)
        )
        msg = f"API call to list authorizations failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization list: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

async def _fetch_vertex_ai_resources(
    ae_project_id: str,
    location: str,
    resource_lister: callable,
    ui_feedback_context: Dict[str, Any],
) -> Tuple[Optional[List[Any]], Optional[str]]:
    button = ui_feedback_context.get("button")
    container = ui_feedback_context.get("container")
    notify_prefix = ui_feedback_context.get("notify_prefix", "Resources")

    if button:
        button.disable()
    notification = ui.notification(
        f"Initializing Vertex AI for {notify_prefix}...",
        spinner=True,
        timeout=None,
        close_button=False,
    )

    init_success, init_error_msg = await asyncio.to_thread(
        init_vertex_ai, ae_project_id, location
    )

    if not init_success:
        notification.dismiss()
        logger.error(
            f"Vertex AI Initialization Failed for {notify_prefix}: {init_error_msg}"
        )
        ui.notify(
            f"Vertex AI Init Failed: {init_error_msg}",
            type="negative",
            multi_line=True,
            close_button=True,
        )
        if container:
            with container:
                container.clear()
                ui.label(f"Vertex AI Init Failed: {init_error_msg}").classes(
                    "text-red-500"
                )
        if button:
            button.enable()
        return None, init_error_msg

    notification.message = f"Vertex AI initialized. Fetching {notify_prefix}..."
    try:

        def fetch_and_convert_to_list():
            return list(resource_lister())

        resources_list = await asyncio.to_thread(fetch_and_convert_to_list)

        notification.spinner = False
        notification.message = f"Found {len(resources_list)} {notify_prefix.lower()}.";
        logger.info(
            f"Found {len(resources_list)} {notify_prefix.lower()} in {ae_project_id}/{location}."
        )
        await asyncio.sleep(1.5)
        notification.dismiss()
        return resources_list, None

    except google_exceptions.PermissionDenied:
        notification.dismiss()
        msg = f"Permission denied for {notify_prefix}. Ensure 'Vertex AI User' role or necessary permissions in '{ae_project_id}'."
        logger.error(msg)
        ui.notify(msg, type="negative", multi_line=True, close_button=True)
        if container:
            with container:
                container.clear()
                ui.label(msg).classes("text-red-500")
        return None, msg
    except Exception as e:
        notification.dismiss()
        msg = f"Failed to list {notify_prefix.lower()}: {e}"
        logger.error(f"{msg}\n{traceback.format_exc()}")
        ui.notify(msg, type="negative", multi_line=True, close_button=True)
        if container:
            with container:
                container.clear()
                ui.label(msg).classes("text-red-500")
        return None, msg
    finally:
        if button:
            button.enable()


def register_agent_sync(
    as_project_id: str,
    as_project_number: str,
    agentspace_app: Dict[str, Any],
    agent_engine_resource_name: str,
    display_name: str,
    description: str,
    tool_description: str,
    icon_uri: str,
    authorizations_list: Optional[List[str]],
) -> Tuple[bool, str]:
    logger.info("\n--- Registering Agent Engine with Agentspace (Sync Call) ---")
    logger.info(
        f"Agentspace Project: {as_project_id} (Number: {as_project_number})"
    )
    logger.info(
        f"Agentspace App: {agentspace_app['engine_id']} (Location: {agentspace_app['location']})"
    )
    logger.info(f"Agent Engine Resource: {agent_engine_resource_name}")
    logger.info(
        f"Display Name: {display_name}, Description: {description}, Tool Desc: {tool_description}, Icon: {icon_uri}, Auths: {authorizations_list}"
    )
    agentspace_app_id = agentspace_app["engine_id"]
    agentspace_location = agentspace_app["location"]

    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh token from ADC for registration.")
            raise ValueError("Failed to refresh token from ADC for registration.")
        access_token = credentials.token
        logger.info("Successfully obtained access token from ADC for registration.")

        hostname = (
            f"{agentspace_location}-discoveryengine.googleapis.com"
            if agentspace_location != "global"
            else "discoveryengine.googleapis.com"
        )
        api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{agentspace_location}/collections/default_collection/engines/{agentspace_app_id}/assistants/default_assistant/agents"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": as_project_id,
        }

        payload = {
            "displayName": display_name,
            "description": description,
            "icon": {
                "uri": icon_uri
                if icon_uri
                else "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"
            },
            "adk_agent_definition": {
                "tool_settings": {"tool_description": tool_description},
                "provisioned_reasoning_engine": {
                    "reasoning_engine": agent_engine_resource_name
                },
            },
        }

        if authorizations_list:
            payload["adk_agent_definition"][
                "authorizations"
            ] = authorizations_list

        log_headers_masked = {
            k: ("Bearer [token redacted]" if k == "Authorization" else v)
            for k, v in headers.items()
        }
        logger.info(
            f"REGISTER_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(payload, indent=2)}"
        )

        response = requests.post(
            api_endpoint, headers=headers, data=json.dumps(payload)
        )
        response.raise_for_status()

        response_data = response.json()
        logger.info(
            f"REGISTER_RESPONSE (Status {response.status_code}):\n{json.dumps(response_data, indent=2)}"
        )
        logger.info(
            f"Successfully created agent resource. Name: {response_data.get('name', 'N/A')}"
        )
        return (
            True,
            f"Successfully created agent resource.\nName: {response_data.get('name', 'N/A')}\nResponse: {json.dumps(response_data, indent=2)}",
        )

    except requests.exceptions.RequestException as e:
        error_detail = (
            f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        )
        msg = f"API call to create authorization failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization creation: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

def get_all_agents_from_assistant_sync(
    as_project_id: str,
    as_project_number: str,
    agentspace_app: Dict[str, Any],
    assistant_name: str = "default_assistant",
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    logger.info(
        f"Fetching all agents from assistant '{assistant_name}', AS Project: {as_project_id}, App: {agentspace_app.get('engine_id')}"
    )
    location = agentspace_app["location"]
    app_id = agentspace_app["engine_id"]
    hostname = (
        f"{location}-discoveryengine.googleapis.com"
        if location != "global"
        else "discoveryengine.googleapis.com"
    )
    api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_name}/agents"

    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token
        if not credentials.token:
            logger.error("Failed to refresh ADC token for agent list.")
            raise ValueError("Failed to refresh ADC token for agent list.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Goog-User-Project": as_project_id,
        }
        log_headers_masked = {
            k: ("Bearer [token redacted]" if k == "Authorization" else v)
            for k, v in headers.items()
        }
        logger.info(
            f"GET_ALL_AGENTS_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}"
        )

        response = requests.get(api_endpoint, headers=headers)
        response.raise_for_status()
        agents_list = response.json().get("agents", [])
        logger.info(
            f"GET_ALL_AGENTS_RESPONSE (Status {response.status_code}): Found {len(agents_list)} agents."
        )
        return agents_list, None
    except requests.exceptions.RequestException as e:
        error_detail = (
            f"Status: {e.response.status_code}, Body: {e.response.text}"
            if e.response
            else str(e)
        )
        msg = f"API Error fetching agent list: {error_detail}"
        logger.error(msg)
        return [], msg
    except Exception as e:
        msg = f"Unexpected error fetching agent list: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return [], msg

def deregister_agent_sync(
    as_project_id: str,
    agent_resource_name: str
) -> Tuple[bool, str]:
    logger.info(
        f"\n--- Deregistering Agent (Sync Call): {agent_resource_name} --- AS Project for header: {as_project_id}"
    )

    try:
        parts = agent_resource_name.split("/")
        loc_idx = parts.index("locations") + 1
        agent_location = parts[loc_idx]
    except (ValueError, IndexError):
        return (
            False,
            f"Could not parse location from agent resource name: {agent_resource_name}",
        )

    logger.info(f"Parsed agent location for deregister: {agent_location}")

    hostname = (
        f"{agent_location}-discoveryengine.googleapis.com"
        if agent_location != "global"
        else "discoveryengine.googleapis.com"
    )
    api_endpoint = f"https://{hostname}/v1alpha/{agent_resource_name}"

    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token
        if not credentials.token:
            logger.error("Failed to refresh ADC token for deregister.")
            raise ValueError("Failed to refresh ADC token for deregister.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Goog-User-Project": as_project_id,
        }
        log_headers_masked = {
            k: ("Bearer [token redacted]" if k == "Authorization" else v)
            for k, v in headers.items()
        }
        logger.info(
            f"DEREGISTER_AGENT_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}"
        )

        response = requests.delete(api_endpoint, headers=headers)
        response.raise_for_status()
        logger.info(
            f"DEREGISTER_AGENT_RESPONSE (Status {response.status_code}): {response.text if response.text else '(empty body)'}"
        )
        logger.info(
            f"Successfully deregistered agent '{agent_resource_name.split('/')[-1]}'."
        )
        return (
            True,
            f"Successfully deregistered agent '{agent_resource_name.split('/')[-1]}'.",
        )
    except requests.exceptions.RequestException as e:
        error_detail = (
            f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        )
        msg = f"API Error during deregistration: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Unexpected error during deregistration: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

# --- Agentspace Lister Functions ---

def _get_auth_details(project_id_override: Optional[str] = None) -> Tuple[google.auth.credentials.Credentials, Optional[str], str]:
    try:
        credentials, project_id_from_adc = google.auth.default(scopes=API_SCOPES)
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        effective_project_id = project_id_override or project_id_from_adc
        if not effective_project_id:
             raise DiscoveryEngineError("Project ID not found. Please provide project_id or run 'gcloud config set project <your-project-id>'")

        logger.info(f"Using Project ID for lookup: {effective_project_id}")
        if not credentials.token:
            raise DiscoveryEngineError("Failed to obtain access token after refreshing credentials.")
        return credentials, credentials.token, effective_project_id
    except google.auth.exceptions.DefaultCredentialsError as e:
        logger.error(f"Authentication error: {e}. Ensure ADC setup ('gcloud auth application-default login').")
        raise DiscoveryEngineError(f"Authentication error: {e}") from e
    except Exception as e:
        logger.error(f"An unexpected error occurred during authentication: {e}")
        raise DiscoveryEngineError(f"An unexpected error occurred during authentication: {e}") from e

def _get_project_number_for_agentspace(project_id: str, credentials: google.auth.credentials.Credentials) -> str:
    try:
        service = build('cloudresourcemanager', 'v1', credentials=credentials)
        project = service.projects().get(projectId=project_id).execute()
        project_number = project.get('projectNumber')
        if project_number:
            logger.info(f"Successfully looked up Project Number for '{project_id}': {project_number}")
            return project_number
        else:
            logger.error(f"Could not find project number for project ID '{project_id}'. Response: {project}")
            raise DiscoveryEngineError(f"Could not find project number for project ID '{project_id}'")
    except HttpError as e:
        logger.error(f"Error calling Cloud Resource Manager API for project '{project_id}': {e}")
        if e.resp.status == 403:
            logger.error("Ensure the Cloud Resource Manager API is enabled and credentials have permissions (e.g., roles/cloudresourcemanager.projectViewer).")
        raise DiscoveryEngineError(f"Cloud Resource Manager API error for project '{project_id}': {e}") from e
    except Exception as e:
        logger.error(f"An unexpected error occurred during project number lookup: {e}")
        raise DiscoveryEngineError(f"An unexpected error occurred during project number lookup: {e}") from e

def _fetch_matching_engines(project_number: str, locations: List[str] | str, access_token: str) -> List[Dict[str, Any]]:
    matching_engines_details = []

    if not access_token:
        logger.error("Missing access token for fetching engines.")
        return []
    if not project_number:
        logger.error("Missing project number for fetching engines.")
        return []

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project_number
    }

    if isinstance(locations, list):
        location_list = [str(loc).strip() for loc in locations if str(loc).strip()]
    elif isinstance(locations, str):
        location_list = [loc.strip() for loc in locations.split(",") if loc.strip()]
    else:
        logger.warning("Invalid 'locations' type provided. Expected list or comma-separated string.")
        return []

    for location in location_list:
        logger.info(f"Checking location via REST: {location} (Project Number: {project_number})")
        api_host = (
            f"{location}-discoveryengine.googleapis.com"
            if location != "global" else "discoveryengine.googleapis.com"
        )
        api_endpoint = f"https://{api_host}/v1beta/projects/{project_number}/locations/{location}/collections/default_collection/engines"

        try:
            logger.debug(f"Calling API: {api_endpoint}")
            response = requests.get(api_endpoint, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            engines_in_response = data.get("engines", [])

            if not engines_in_response:
                logger.info(f"No engines found in {location} under default_collection.")
                continue

            logger.info(f"Found {len(engines_in_response)} engine(s) in {location}. Checking for 'subscription_tier_search_and_assistant' tier...")
            engines_matched_in_location = 0
            for engine in engines_in_response:
                search_config = engine.get("searchEngineConfig")
                retrieved_tier = search_config.get("requiredSubscriptionTier") if search_config else None

                if retrieved_tier and retrieved_tier.lower() == "subscription_tier_search_and_assistant":
                        engines_matched_in_location += 1
                        engine_id = engine.get("name", "N/A").split('/')[-1]
                        tier = search_config.get("requiredSubscriptionTier")
                        matching_engines_details.append({
                            "engine_id": engine_id,
                            "location": location,
                            "tier": tier
                        })
                        logger.debug(f"  Match found - Engine ID: {engine_id}, Location: {location}, Tier: {tier}")
                elif retrieved_tier:
                    logger.debug(f"  Skipping engine {engine.get('name', 'N/A').split('/')[-1]} in {location} - Tier is '{retrieved_tier}' (not 'subscription_tier_search_and_assistant').")

            if engines_matched_in_location == 0:
                logger.info(f"No engines in {location} matched the requiredSubscriptionTier criteria.")

        except requests.exceptions.Timeout:
             logger.warning(f"Timeout calling API for location {location}: {api_endpoint}")
        except requests.exceptions.RequestException as e:
             logger.error(f"Error calling API for location {location}: {e}")
             if isinstance(e, requests.exceptions.HTTPError):
                 try:
                     logger.error(f"Response Body: {e.response.text}")
                 except Exception:
                     logger.error("Could not read error response body.")
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON response for location {location}.")
        except Exception as e:
             logger.error(f"An unexpected error occurred processing location {location}: {e}")

    return matching_engines_details

def get_agentspace_apps_from_projectid(project_id: str, locations: List[str] | str = AGENTSPACE_DEFAULT_LOCATIONS) -> List[Dict[str, Any]]:
    try:
        credentials, access_token, _ = _get_auth_details(project_id_override=project_id)
        if not access_token:
            raise DiscoveryEngineError("Failed to obtain access token during authentication.")

        project_number = _get_project_number_for_agentspace(project_id, credentials)

        matching_engines = _fetch_matching_engines(project_number, locations, access_token)

        logger.info(f"Found {len(matching_engines)} engine(s) with tier 'subscription_tier_search_and_assistant'.")
        return matching_engines

    except DiscoveryEngineError as e:
        logger.error(f"Failed to get agentspace apps: {e}")
        return []
    except Exception as e:
        logger.exception(f"An unexpected critical error occurred in get_agentspace_apps_from_projectid: {e}")
        return []

async def fetch_agentspace_apps(
    project_id: str,
    locations: str,
    select_ui: ui.select,
    button: ui.button,
    page_state: Dict[str, Any],
    state_key: str,
) -> None:
    if not project_id:
        ui.notify("Please enter a Project ID.", type="warning")
        return

    logger.info(
        f"Fetching Agentspace apps for project '{project_id}' in locations: {locations}"
    )
    button.disable()
    select_ui.set_visibility(False)
    select_ui.clear()
    page_state[state_key] = []

    notification = ui.notification(
        f"Fetching Agentspace apps from '{project_id}'...",
        spinner=True,
        timeout=None,
        close_button=False,
    )

    try:
        agentspaces = await asyncio.to_thread(
            get_agentspace_apps_from_projectid, project_id, locations
        )

        if not agentspaces:
            msg = f"No Agentspace apps found in project '{project_id}' for locations '{locations}'. Check project, locations, and permissions."
            logger.warning(msg)
            notification.message = msg
            notification.type = "warning"
            await asyncio.sleep(3)
        else:
            page_state[state_key] = agentspaces
            options = {
                f"{app['location']}/{app['engine_id']}": f"{app['engine_id']} ({app['location']})"
                for app in agentspaces
            }
            select_ui.options = options
            select_ui.set_visibility(True)
            logger.info(
                f"Successfully fetched {len(agentspaces)} Agentspace apps. UI updated."
            )
            notification.message = (
                f"Found {len(agentspaces)} Agentspace app(s)."
            )
            notification.spinner = False
            await asyncio.sleep(1.5)

    except Exception as e:
        msg = f"An unexpected error occurred while fetching Agentspace apps: {e}"
        logger.error(f"{msg}\n{traceback.format_exc()}")
        notification.message = msg
        notification.type = "negative"
        notification.multi_line = True
        notification.close_button = True
    finally:
        if 'notification' in locals() and notification:
            notification.dismiss()
        button.enable()
        select_ui.update()

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
                                       (value.startswith("'') and value.endswith("'"))):
                    value = value[1:-1]

                if key: # Ensure key is not empty
                    env_vars[key] = value
    except IOError as e:
        print(f"Warning: Could not read .env file at {dotenv_path}. Error: {e}", file=sys.stderr)
        return {} # Return empty if file read fails

    return env_vars