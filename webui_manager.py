#  Copyright (C) 2025 Google LLC
#
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

# --- Version ---
__version__ = "0.3"

# --- Standard Library Imports ---
import asyncio
import copy
import importlib
import json
import logging  # Added for logging
import os
import re
import sys
import time
import traceback
from logging.handlers import TimedRotatingFileHandler  # Added for logging
from typing import Any, Dict, List, Optional, Tuple

import vertexai
from dotenv import load_dotenv
from google.api_core import exceptions as google_exceptions
from nicegui import Client, ui
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

# --- Google Cloud & Auth Imports ---
try:
    import google.auth
    import google.auth.transport.requests
    import requests
    from google.cloud import resourcemanager_v3
except ImportError as e:
    print(f"Error: Could not import Google API libraries. {e}")
    print("Please install them: pip install requests google-auth google-cloud-resource-manager")
    sys.exit(1)

# --- Configuration Loading ---
try:
    from deployment_utils.agentspace_lister import (
        get_agentspace_apps_from_projectid,  # Used for Register & Deregister
    )
    from deployment_utils.constants import (
        SUPPORTED_REGIONS,
        WEBUI_AGENTDEPLOYMENT_HELPTEXT,
    )  # Import the help text
    from deployment_utils.deployment_configs import (
        AGENT_CONFIGS,  # Used for Deploy & Register
    )
except ImportError as e:
    print(
        "Error: Could not import from 'deployment_utils'. "
        f"Ensure 'deployment_configs.py' and 'constants.py' exist. Details: {e}"
    )
    AGENT_CONFIGS = {"error": {"ae_display_name": "Import Error"}}
    SUPPORTED_REGIONS = ["us-central1"]
    WEBUI_AGENTDEPLOYMENT_HELPTEXT = "Error: Help text constant not found." # Fallback
    get_agentspace_apps_from_projectid = None # Indicate function is missing
    IMPORT_ERROR_MESSAGE = (
        "Failed to import 'AGENT_CONFIGS', 'SUPPORTED_REGIONS', 'WEBUI_AGENTDEPLOYMENT_HELPTEXT', or 'get_agentspace_apps_from_projectid' from 'deployment_utils'. "
        "Please ensure 'deployment_configs.py', 'constants.py', and 'agentspace_lister.py' exist in the 'deployment_utils' directory "
        "relative to this script, and that the directory contains an `__init__.py` file. Run: pip install -r requirements.txt"
    )
else:
    IMPORT_ERROR_MESSAGE = None

# Import for loading .env files
from deployment_utils.deployment_helpers import load_env_variables

# --- Constants ---
_BASE_REQUIREMENTS = [
    "python-dotenv",
    "requests",
    "google-cloud-resource-manager",
]
AS_AUTH_API_BASE_URL = "https://discoveryengine.googleapis.com/v1alpha"
AS_AUTH_DEFAULT_LOCATION = "global"  # Authorizations are typically global

# --- Logger Setup for webui_manager.py ---
MANAGER_LOG_FILE_NAME = "webui_manager_activity.log"
script_dir_manager = os.path.dirname(os.path.abspath(__file__))
manager_log_file_path = os.path.join(script_dir_manager, MANAGER_LOG_FILE_NAME)

logger = logging.getLogger("WebUIManagerActivity")
logger.setLevel(logging.INFO)

manager_file_handler = TimedRotatingFileHandler(
    manager_log_file_path,
    when="midnight",
    interval=1,
    backupCount=7, # Keep 7 days of logs
    encoding='utf-8'
)
manager_file_handler.setLevel(logging.INFO)
manager_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s')
manager_file_handler.setFormatter(manager_formatter)
logger.addHandler(manager_file_handler)
logger.propagate = False
# --- Helper Functions ---

def init_vertex_ai(project_id: str, location: str, staging_bucket: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Initializes Vertex AI SDK. Staging bucket is optional.
    Returns:
        Tuple[bool, Optional[str]]: (success_status, error_message_or_none)
    """
    try:
        bucket_info = f"(Bucket: gs://{staging_bucket})" if staging_bucket else "(No bucket specified)"
        logger.info(f"Initializing Vertex AI SDK for {project_id}/{location} {bucket_info}...")
        init_kwargs = {"project": project_id, "location": location}
        if staging_bucket:
            init_kwargs["staging_bucket"] = f"gs://{staging_bucket}"
        vertexai.init(**init_kwargs)
        logger.info("Vertex AI initialized successfully.")
        return True, None
    except google_exceptions.NotFound:
        bucket_error = f"or Bucket 'gs://{staging_bucket}' invalid/inaccessible" if staging_bucket else ""
        msg = f"Error: Project '{project_id}' or Location '{location}' not found, or Vertex AI API not enabled, {bucket_error}."
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Error initializing Vertex AI SDK: {e}"
        logger.error(msg)
        return False, msg

def get_project_number_sync(project_id: str) -> Optional[str]:
    """Gets the GCP project number from the project ID (Synchronous version)."""
    try:
        client = resourcemanager_v3.ProjectsClient()
        request = resourcemanager_v3.GetProjectRequest(name=f"projects/{project_id}")
        project = client.get_project(request=request)
        return project.name.split('/')[-1]
    except Exception as e:
        logger.error(f"Error getting project number for '{project_id}': {e}")
        return None

async def get_project_number(project_id: str) -> Optional[str]:
    """Gets the GCP project number from the project ID (Async wrapper)."""
    if not project_id: return None
    return await asyncio.to_thread(get_project_number_sync, project_id)


async def get_agent_root_nicegui(agent_config: dict) -> Tuple[Optional[Any], dict[str, str], Optional[str]]:
    """
    Dynamically imports the root_agent for deployment.
    Also loads agent-specific .env variables into os.environ before import
    and returns them.
    """
    module_path = agent_config.get("module_path")
    var_name = agent_config.get("root_variable")
    agent_loaded_env_vars: dict[str, str] = {}

    if not module_path or not var_name:
        error_msg = (
            "Agent configuration is missing 'module_path' or 'root_variable'.\n"
            f"Config provided: {agent_config}"
        )
        logger.error(f"Agent Import Error: {error_msg}")
        return None, agent_loaded_env_vars, error_msg

    try:
        print(f"Importing '{var_name}' from module '{module_path}'...")

        # Load agent-specific .env variables *before* importing the module
        env_file_relative_to_deploy_script = agent_config.get("local_env_file")
        if env_file_relative_to_deploy_script:
            env_file_relative_to_helpers = os.path.join("..", env_file_relative_to_deploy_script.lstrip("./"))
            loaded_vars = load_env_variables(env_file_relative_to_helpers)
            if loaded_vars:
                logger.info(f"Updating deployment script's environment with {len(loaded_vars)} variables from agent's .env file.")
                os.environ.update(loaded_vars)
                agent_loaded_env_vars = loaded_vars # Store for returning

        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path: sys.path.insert(0, script_dir)
        parent_dir = os.path.dirname(script_dir)
        if parent_dir not in sys.path: sys.path.insert(0, parent_dir)

        agent_module = importlib.import_module(module_path)
        root_agent = getattr(agent_module, var_name)
        logger.info(f"Successfully imported root agent '{var_name}' from '{module_path}'.")
        return root_agent, agent_loaded_env_vars, None
    except ImportError:
        tb_str = traceback.format_exc()
        error_msg = (
            f"Failed to import module '{module_path}'.\n"
            "Check 'module_path' in deployment_configs.py and ensure the module exists.\n\n"
            f"Traceback: {tb_str}"
        )
        logger.error(f"Agent Import Error: {error_msg}")
        return None, agent_loaded_env_vars, error_msg
    except AttributeError:
        error_msg = (
            f"Module '{module_path}' does not have an attribute named '{var_name}'.\n"
            "Check 'root_variable' in deployment_configs.py."
        )
        logger.error(f"Agent Import Error: {error_msg}")
        return None, agent_loaded_env_vars, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred during agent import: {e}\n{traceback.format_exc()}"
        logger.error(f"Agent Import Error: {error_msg}")
        return None, agent_loaded_env_vars, error_msg

async def update_timer(start_time: float, timer_label: ui.label, stop_event: asyncio.Event, status_area: ui.element):
    """Updates the timer label every second until stop_event is set."""
    while not stop_event.is_set():
        elapsed_seconds = time.monotonic() - start_time
        minutes, seconds = divmod(int(elapsed_seconds), 60)
        time_str = f"{minutes:02d}:{seconds:02d}"
        try:
            with status_area: # Use the specific status area passed
                timer_label.set_text(f"Elapsed Time: {time_str}")
        except Exception as e:
            logger.warning(f"Error updating timer UI: {e}") # Changed to warning as it's not critical
            break
        await asyncio.sleep(1)

# --- Authorization Management Helper Functions (Adapted from webui_as_authentication.py) ---

def get_access_token_and_credentials_sync_webui() -> tuple[str | None, google.auth.credentials.Credentials | None, str | None]:
    """Gets ADC access token and credentials synchronously for webui_manager."""
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

async def get_access_token_and_credentials_async_webui() -> tuple[str | None, google.auth.credentials.Credentials | None, str | None]:
    """Gets ADC access token and credentials asynchronously for webui_manager."""
    return await asyncio.to_thread(get_access_token_and_credentials_sync_webui)

def create_authorization_sync_webui(
    target_project_id: str, # For X-Goog-User-Project header
    target_project_number: str, # For URL path and payload name
    auth_id: str,
    client_id: str,
    client_secret: str,
    auth_uri: str,
    token_uri: str,
    access_token: str
) -> tuple[bool, str]:
    """Synchronous function to create an Agentspace Authorization for webui_manager."""
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
        }
    }
    try:
        logger.info(f"Attempting to create authorization: {auth_id} in project {target_project_id} (number: {target_project_number})")
        logged_payload = copy.deepcopy(payload)
        if "serverSideOauth2" in logged_payload and "clientSecret" in logged_payload["serverSideOauth2"]:
            logged_payload["serverSideOauth2"]["clientSecret"] = "[redacted]"
        log_headers = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.info(f"CREATE_AUTHORIZATION_REQUEST:\nURL: {url}\nHeaders: {json.dumps(log_headers, indent=2)}\nPayload: {json.dumps(logged_payload, indent=2)}")

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"CREATE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}")
        return True, f"Successfully created authorization '{auth_id}'.\nResponse: {json.dumps(response_json, indent=2)}"
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
        msg = f"API call to create authorization failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization creation: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

def delete_authorization_sync_webui(
    target_project_id: str, # For X-Goog-User-Project header
    target_project_number: str, # For URL path
    auth_id: str,
    access_token: str
) -> tuple[bool, str]:
    """Synchronous function to delete an Agentspace Authorization for webui_manager."""
    url = f"{AS_AUTH_API_BASE_URL}/projects/{target_project_number}/locations/{AS_AUTH_DEFAULT_LOCATION}/authorizations/{auth_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": target_project_id,
    }
    try:
        logger.info(f"Attempting to delete authorization: {auth_id} in project {target_project_id} (number: {target_project_number})")
        log_headers = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.info(f"DELETE_AUTHORIZATION_REQUEST:\nURL: {url}\nHeaders: {json.dumps(log_headers, indent=2)}")

        response = requests.delete(url, headers=headers)
        response.raise_for_status()
        logger.info(f"DELETE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{response.text if response.text else '(empty body)'}")
        return True, f"Successfully deleted authorization '{auth_id}'. Status: {response.status_code}"
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
        msg = f"API call to delete authorization failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization deletion: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

# --- Deployment Logic ---
async def run_deployment_async(
    ae_project_id: str, location: str, bucket: str, # Use ae_project_id
    agent_name: str, agent_config: dict, display_name: str, description: str,
    deploy_button: ui.button, status_area: ui.column,
) -> None:
    """Performs the agent deployment steps asynchronously."""
    deploy_button.disable()
    logger.info(f"Starting deployment for agent: {agent_name} in {ae_project_id}/{location}, bucket: {bucket}.")
    logger.info(f"Display Name: {display_name}, Description: {description}")


    status_area.clear()

    timer_label = None
    stop_timer_event = asyncio.Event()

    with status_area:
        ui.label(f"Starting deployment for: {agent_name}").classes("text-lg font-semibold")
        progress_label = ui.label("Initializing Vertex AI SDK...")
        spinner = ui.spinner(size="lg", color="primary")
        timer_label = ui.label("Elapsed Time: 00:00").classes("text-sm text-gray-500 mt-1")

    init_success, init_error_msg = await asyncio.to_thread(init_vertex_ai, ae_project_id, location, bucket)

    if not init_success:
        spinner.set_visibility(False)
        logger.error(f"Vertex AI Initialization Failed for deployment: {init_error_msg}")
        with status_area: progress_label.set_text(f"Error: {init_error_msg}")
        ui.notify(f"Vertex AI Initialization Failed: {init_error_msg}", type="negative", multi_line=True, close_button=True)
        deploy_button.enable()
        return

    with status_area:
        progress_label.set_text("Vertex AI Initialized. Importing agent code...")
        ui.notify("Vertex AI Initialized Successfully.", type="positive")

    root_agent, agent_env_vars, import_error_msg = await get_agent_root_nicegui(agent_config)
    if root_agent is None:
        spinner.set_visibility(False)
        logger.error(f"Agent Import Failed for deployment: {import_error_msg}")
        with status_area: progress_label.set_text(f"Error: {import_error_msg}")
        ui.notify(f"Agent Import Failed: {import_error_msg}", type="negative", multi_line=True, close_button=True)
        deploy_button.enable()
        return

    with status_area: progress_label.set_text("Agent code imported. Preparing deployment...")

    adk_app = AdkApp(agent=root_agent, enable_tracing=True)
    agent_specific_reqs = agent_config.get("requirements", [])
    if not isinstance(agent_specific_reqs, list): agent_specific_reqs = []
    combined_requirements = sorted(list(set(_BASE_REQUIREMENTS) | set(agent_specific_reqs)))
    extra_packages = agent_config.get("extra_packages", [])
    if not isinstance(extra_packages, list): extra_packages = []

    with status_area: progress_label.set_text("Configuration ready. Deploying ADK to Agent Engine (this may take 2-5 minutes)...")
    
    log_message_details = f"\n--- Deployment Details for {agent_name} ---\n"
    log_message_details += f"Display Name: {display_name}\n"
    log_message_details += f"Description: {description}\n"
    log_message_details += f"Requirements: {combined_requirements}\n"
    log_message_details += f"Extra Packages: {extra_packages}\n"
    if agent_env_vars:
        log_message_details += "Environment Variables from Agent's .env file:\n"
        for key, val in agent_env_vars.items():
            log_message_details += f"- {key}={'[value_set]' if val else '[empty_value]'}\n" # Avoid logging sensitive env values
        with status_area:
            ui.label("Loaded Environment Variables from Agent's .env:").classes("font-semibold mt-2")
            for key, val in agent_env_vars.items(): ui.label(f"- {key}: {val[:30]}{'...' if len(val)>30 else ''}").classes("text-xs")
    logger.info(log_message_details + "--------------------------")

    start_time = time.monotonic()
    _ = asyncio.create_task(update_timer(start_time, timer_label, stop_timer_event, status_area))
    remote_agent = None
    deployment_error = None
    try:
        def sync_create_agent():
            return agent_engines.create(
                adk_app, requirements=combined_requirements, extra_packages=extra_packages,
                display_name=display_name, description=description, env_vars=agent_env_vars
            )
        remote_agent = await asyncio.to_thread(sync_create_agent)
    except Exception as e:
        deployment_error = e
        tb_str = traceback.format_exc()
        logger.error(f"--- Agent creation failed for {agent_name} ---\n{tb_str}")
    finally:
        stop_timer_event.set()
        await asyncio.sleep(0.1)
        end_time = time.monotonic()
        duration = end_time - start_time
        duration_str = time.strftime("%M:%S", time.gmtime(duration))
        spinner.set_visibility(False)

        with status_area:
            timer_label.set_text(f"Final Elapsed Time: {duration_str}")

        if remote_agent:
            success_msg = f"Successfully created remote agent: {remote_agent.resource_name}"
            logger.info(f"--- Agent creation complete for {agent_name} ({duration_str}) --- Resource: {remote_agent.resource_name}")
            with status_area:
                 progress_label.set_text(f"Deployment Successful! (Duration: {duration_str})")
                 ui.label("Resource Name:").classes("font-semibold mt-2")
                 ui.markdown(f"`{remote_agent.resource_name}`").classes("text-sm")
                 ui.notify(success_msg, type="positive", multi_line=True, close_button=True)
        else:
            error_msg = f"Error during agent engine creation: {deployment_error}"
            logger.error(f"Deployment Failed for {agent_name}! (Duration: {duration_str}). Error: {deployment_error}\nTraceback: {traceback.format_exc()}")
            with status_area:
                 progress_label.set_text(f"Deployment Failed! (Duration: {duration_str})")
                 ui.label("Error Details:").classes("font-semibold mt-2 text-red-600")
                 ui.html(f"<pre class='text-xs p-2 bg-gray-100 dark:bg-gray-800 rounded overflow-auto'>{traceback.format_exc()}</pre>")
                 ui.notify(error_msg, type="negative", multi_line=True, close_button=True)
        
        deploy_button.enable()

# --- Destruction Logic ---

# --- Refactored Helper for Fetching Vertex AI Resources ---
async def _fetch_vertex_ai_resources(
    ae_project_id: str,
    location: str,
    resource_lister: callable, # e.g., agent_engines.list
    ui_feedback_context: Dict[str, Any], # e.g., {'button': fetch_button, 'container': list_container, 'notify_prefix': "Resources"}
) -> Tuple[Optional[List[Any]], Optional[str]]:
    """
    Common logic to initialize Vertex AI and list resources.
    Returns (list_of_resources, error_message_or_none)
    """
    button = ui_feedback_context.get('button')
    container = ui_feedback_context.get('container') # Optional, for clearing/error display
    notify_prefix = ui_feedback_context.get('notify_prefix', "Resources")

    if button: button.disable()
    # Initial notification using a persistent object for updates
    notification = ui.notification(f"Initializing Vertex AI for {notify_prefix}...", spinner=True, timeout=None, close_button=False)

    init_success, init_error_msg = await asyncio.to_thread(init_vertex_ai, ae_project_id, location)

    if not init_success:
        notification.dismiss()
        logger.error(f"Vertex AI Initialization Failed for {notify_prefix}: {init_error_msg}")
        ui.notify(f"Vertex AI Init Failed: {init_error_msg}", type="negative", multi_line=True, close_button=True)
        if container: # Display error in a dedicated container if provided
            with container: container.clear(); ui.label(f"Vertex AI Init Failed: {init_error_msg}").classes("text-red-500")
        if button: button.enable()
        return None, init_error_msg

    notification.message = f"Vertex AI initialized. Fetching {notify_prefix}..."
    try:
        resources_generator = await asyncio.to_thread(resource_lister)
        resources_list = list(resources_generator) # Convert generator to list

        notification.spinner = False # Stop spinner once fetched
        notification.message = f"Found {len(resources_list)} {notify_prefix.lower()}."
        logger.info(f"Found {len(resources_list)} {notify_prefix.lower()} in {ae_project_id}/{location}.")
        await asyncio.sleep(1.5) # Let notification show briefly
        notification.dismiss()
        return resources_list, None

    except google_exceptions.PermissionDenied:
        notification.dismiss()
        msg = f"Permission denied for {notify_prefix}. Ensure 'Vertex AI User' role or necessary permissions in '{ae_project_id}'."
        logger.error(msg)
        ui.notify(msg, type="negative", multi_line=True, close_button=True)
        if container:
            with container: container.clear(); ui.label(msg).classes("text-red-500")
        return None, msg
    except Exception as e:
        notification.dismiss()
        msg = f"Failed to list {notify_prefix.lower()}: {e}"
        logger.error(f"{msg}\n{traceback.format_exc()}")
        ui.notify(msg, type="negative", multi_line=True, close_button=True)
        if container:
            with container: container.clear(); ui.label(msg).classes("text-red-500")
        return None, msg
    finally:
        if button: button.enable()

async def fetch_agents_for_destroy(
    ae_project_id: str, location: str, # Use ae_project_id
    list_container: ui.column, delete_button: ui.button, fetch_button: ui.button,
    page_state: dict
) -> None:
    """Fetches agent engines for the destroy tab."""
    fetch_button.disable()
    list_container.clear()
    page_state["destroy_agents"] = []
    page_state["destroy_selected"] = {}
    delete_button.disable()

    with list_container: # Use list_container for initial messages
        ui.label("Fetching Agent Engines...").classes("text-gray-500")

    existing_agents, error_msg = await _fetch_vertex_ai_resources(
        ae_project_id,
        location,
        agent_engines.list,
        ui_feedback_context={'button': fetch_button, 'container': list_container, 'notify_prefix': "Agent Engines"}
    )

    list_container.clear() # Clear "Fetching..." message
    if error_msg:
        # _fetch_vertex_ai_resources already handles notifications and logging
        # It also re-enables the button.
        fetch_button.enable()
        return
    if existing_agents is not None: # Check if None, not just empty list

        if not existing_agents:
            page_state["destroy_agents"] = []
            with list_container:
                ui.label("0 Available Agent Engines").classes("text-lg font-semibold mb-2")
                ui.label(f"No agent engines found in {ae_project_id}/{location}.")
            ui.notify("No agent engines found.", type="info")
        else:
            with list_container:
                page_state["destroy_agents"] = existing_agents
                ui.label(f"{len(existing_agents)} Available Agent Engines:").classes("text-lg font-semibold mb-2")
                for agent in existing_agents:
                    resource_name = agent.resource_name
                    create_time_str = agent.create_time.strftime('%Y-%m-%d %H:%M:%S %Z') if agent.create_time else "N/A"
                    update_time_str = agent.update_time.strftime('%Y-%m-%d %H:%M:%S %Z') if agent.update_time else "N/A"
                    description_str = "No description."
                    if hasattr(agent, '_gca_resource') and hasattr(agent._gca_resource, 'description') and agent._gca_resource.description:
                        description_str = agent._gca_resource.description

                    card = ui.card().classes("w-full mb-2 p-3")
                    with card:
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label(f"{agent.display_name}").classes("text-lg font-medium")
                        with ui.column().classes("gap-0 mt-1 text-sm text-gray-600 dark:text-gray-400"):
                            ui.label(f"Resource: {resource_name}")
                            ui.label(f"Description: {description_str}")
                            with ui.row().classes("gap-4 items-center"):
                                ui.label(f"Created: {create_time_str}")
                                ui.label(f"Updated: {update_time_str}")
                        checkbox = ui.checkbox("Select for Deletion")
                        checkbox.bind_value(page_state["destroy_selected"], resource_name)
                        checkbox.classes("absolute top-2 right-2")
            delete_button.enable()

async def confirm_and_delete_agents(
    ae_project_id: str, location: str, page_state: dict # Use ae_project_id
) -> None:
    """Shows confirmation dialog and proceeds with deletion if confirmed."""
    selected_map = page_state.get("destroy_selected", {})
    agents_to_delete = [name for name, selected in selected_map.items() if selected]

    if not agents_to_delete:
        ui.notify("No agents selected for deletion.", type="warning")
        return
    logger.info(f"Confirmation requested for deleting agents: {agents_to_delete} from {ae_project_id}/{location}.")

    with ui.dialog() as dialog, ui.card():
        ui.label("Confirm Deletion").classes("text-xl font-bold")
        ui.label("You are about to permanently delete the following agent(s):")
        for name in agents_to_delete:
            agent_display = name
            for agent in page_state.get("destroy_agents", []):
                if agent.resource_name == name:
                    agent_display = f"{agent.display_name} ({name.split('/')[-1]})"
                    break
            ui.label(f"- {agent_display}")
        ui.label("\nThis action cannot be undone.").classes("font-bold text-red-600")

        with ui.row().classes("mt-4 w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close, color="gray")
            ui.button("Delete Permanently",
                      on_click=lambda: run_actual_deletion(ae_project_id, location, agents_to_delete, page_state, dialog),
                      color="red")
    await dialog

async def run_actual_deletion(
    ae_project_id: str, location: str, resource_names: List[str], page_state: dict, dialog: ui.dialog # Use ae_project_id
) -> None:
    """Performs the actual deletion of agents."""
    dialog.close()

    init_success, init_error_msg = await asyncio.to_thread(init_vertex_ai, ae_project_id, location)
    logger.info(f"Starting actual deletion of agents: {resource_names} from {ae_project_id}/{location}.")
    if not init_success:
        full_msg = f"Failed to re-initialize Vertex AI. Deletion aborted.\nDetails: {init_error_msg}" if init_error_msg else "Failed to re-initialize Vertex AI. Deletion aborted."
        logger.error(f"Vertex AI re-initialization failed before deletion: {full_msg}")
        ui.notify(full_msg, type="negative", multi_line=True, close_button=True)
        return

    logger.info(f"\n--- Deleting Selected Agents from {ae_project_id}/{location} ---")
    progress_notification = ui.notification(timeout=None, close_button=False)

    success_count = 0
    fail_count = 0
    failed_agents: List[str] = []

    def delete_single_agent(resource_name_to_delete):
        agent_to_delete = agent_engines.get(resource_name=resource_name_to_delete)
        agent_to_delete.delete(force=True)

    for i, resource_name in enumerate(resource_names):
        try:
            progress_notification.message = f"Deleting {i+1}/{len(resource_names)}: {resource_name.split('/')[-1]}..."
            progress_notification.spinner = True
            logger.info(f"Attempting to delete agent: {resource_name}")
            await asyncio.to_thread(delete_single_agent, resource_name)
            logger.info(f"Successfully deleted agent: {resource_name}")
            ui.notify(f"Successfully deleted {resource_name.split('/')[-1]}", type="positive")
            success_count += 1
            if resource_name in page_state.get("destroy_selected", {}):
                 del page_state["destroy_selected"][resource_name]
            page_state["destroy_agents"] = [a for a in page_state.get("destroy_agents", []) if a.resource_name != resource_name]

        except Exception as e:
            error_msg = f"Failed to delete {resource_name.split('/')[-1]}: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            ui.notify(error_msg, type="negative", multi_line=True, close_button=True)
            fail_count += 1
            failed_agents.append(resource_name)
        finally:
            progress_notification.spinner = False

    progress_notification.dismiss()
    logger.info(f"--- Deletion process finished for {ae_project_id}/{location}. Success: {success_count}, Fail: {fail_count} ---")

    summary_title = "Deletion Complete" if fail_count == 0 else "Deletion Finished with Errors"
    with ui.dialog() as summary_dialog, ui.card():
        ui.label(summary_title).classes("text-xl font-bold")
        ui.label(f"Successfully deleted: {success_count}")
        ui.label(f"Failed to delete: {fail_count}")
        if failed_agents:
            ui.label("Failed agents:")
            for name in failed_agents: ui.label(f"- {name.split('/')[-1]}")
        with ui.row().classes("mt-4 w-full justify-end"):
            ui.button("OK", on_click=summary_dialog.close)
    await summary_dialog

# --- Registration Logic ---

async def fetch_agent_engines_for_register(
    ae_project_id: str, location: str, # Use ae_project_id
    select_element: ui.select, fetch_button: ui.button, page_state: dict, next_button: ui.button
) -> None:
    """Fetches deployed Agent Engines for the registration tab."""
    next_button.disable()
    fetch_button.disable()
    select_element.clear()
    select_element.set_value(None)
    page_state["register_agent_engines"] = []
    select_element.set_visibility(False) # Hide select until populated

    existing_agents, error_msg = await _fetch_vertex_ai_resources(
        ae_project_id,
        location,
        agent_engines.list,
        ui_feedback_context={'button': fetch_button, 'notify_prefix': "Agent Engines"}
    )

    if error_msg:
        # _fetch_vertex_ai_resources handles notifications and re-enables button
        fetch_button.enable()
        return
    
    if existing_agents is not None:
        page_state["register_agent_engines"] = existing_agents

        if not existing_agents:
            ui.notify("No deployed Agent Engines found.", type="info")
            logger.info(f"No deployed Agent Engines found in {ae_project_id}/{location} for registration.")
            select_element.set_options([])
        else:
            options = {}
            for agent in existing_agents:
                create_time_str = agent.create_time.strftime('%Y-%m-%d %H:%M') if agent.create_time else "N/A"
                update_time_str = agent.update_time.strftime('%Y-%m-%d %H:%M') if agent.update_time else "N/A"
                display_text = (f"{agent.display_name} ({agent.resource_name.split('/')[-1]}) | "
                                f"Created: {create_time_str} | Updated: {update_time_str}")
                options[agent.resource_name] = display_text
            select_element.set_options(options)
            logger.info(f"Found {len(existing_agents)} Agent Engines in {ae_project_id}/{location} for registration.")
            # Notification is handled by _fetch_vertex_ai_resources

        select_element.set_visibility(True)
    fetch_button.enable() # Ensure button is enabled if no error but list is empty


async def fetch_agentspace_apps(
    as_project_id: str, locations: List[str], # Use as_project_id
    select_element: ui.select, fetch_button: ui.button, page_state: dict, state_key: str, next_button: Optional[ui.button] = None
) -> None:
    """Fetches Agentspace Apps (Discovery Engine Engines) for selection."""
    if not as_project_id or not locations:
        ui.notify("Please provide Agentspace Project ID and Agentspace Locations.", type="warning")
        return
    logger.info(f"Fetching Agentspace Apps from project {as_project_id} in locations: {locations}.")

    if next_button: next_button.disable()
    select_element.set_visibility(False)

    if not get_agentspace_apps_from_projectid:
        logger.error("'get_agentspace_apps_from_projectid' function not available.")
        ui.notify("Error: 'get_agentspace_apps_from_projectid' function not available.", type="negative")
        if next_button: next_button.enable()
        return

    fetch_button.disable()
    select_element.clear()
    select_element.set_value(None)
    page_state[state_key] = []
    locations_display = ", ".join(locations)
    ui.notify(f"Fetching Agentspace Apps in {locations_display}...", type="info", spinner=True)

    try:
        project_agentspaces = await asyncio.to_thread(
            get_agentspace_apps_from_projectid, as_project_id, locations=locations
        )
        page_state[state_key] = project_agentspaces

        if not project_agentspaces:
            ui.notify("No Agentspace Apps found for the specified locations.", type="info")
            logger.info(f"No Agentspace Apps found in {as_project_id} for locations {locations}.")
            select_element.set_options([])
        else:
            options = {f"{app['location']}/{app['engine_id']}": f"ID: {app['engine_id']} (Loc: {app['location']}, Tier: {app['tier']})"
                       for app in project_agentspaces}
            select_element.set_options(options)
            logger.info(f"Found {len(project_agentspaces)} Agentspace Apps in {as_project_id} for locations {locations}.")
            ui.notify(f"Found {len(project_agentspaces)} Agentspace Apps.", type="positive")

    except Exception as e:
        select_element.set_visibility(False)
        ui.notify(f"Error fetching Agentspace Apps: {e}", type="negative", multi_line=True, close_button=True)
        logger.error(f"Error fetching Agentspace Apps: {e}\n{traceback.format_exc()}")
    finally:
        select_element.set_visibility(True)
        fetch_button.enable()

def register_agent_with_agentspace_sync(
    as_project_id: str, as_project_number: str, # Use as_project_id and as_project_number
    agentspace_app: Dict[str, Any],
    agent_engine_resource_name: str, agent_display_name: str, agent_description: str,
    agent_icon_uri: str, default_assistant_name: str = "default_assistant"
) -> Tuple[bool, str]:
    """Synchronous function to register Agent Engine with Agentspace App."""
    logger.info(f"\n--- Registering Agent Engine (Legacy) with Agentspace ---")  # noqa: F541
    logger.info(f"Agentspace Project: {as_project_id} (Number: {as_project_number})")
    logger.info(f"Agentspace App: {agentspace_app['engine_id']} (Location: {agentspace_app['location']})")
    logger.info(f"Agent Engine Resource: {agent_engine_resource_name}")
    logger.info(f"Display Name: {agent_display_name}, Description: {agent_description}, Icon: {agent_icon_uri}")
    agentspace_app_id = agentspace_app['engine_id']
    agentspace_location = agentspace_app['location']

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh token from ADC for legacy registration.")
            raise ValueError("Failed to refresh token from ADC for legacy registration.")
        access_token = credentials.token
        logger.info("Successfully obtained access token from ADC for legacy registration.")

        agent_id = re.sub(r'\W+', '_', agent_display_name.lower())[:50]
        logger.info(f"Using Agent Config ID (Legacy): {agent_id}")

        hostname = f"{agentspace_location}-discoveryengine.googleapis.com" if agentspace_location != "global" else "discoveryengine.googleapis.com"
        assistant_api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{agentspace_location}/collections/default_collection/engines/{agentspace_app_id}/assistants/{default_assistant_name}"

        common_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-goog-user-project": as_project_id, # Use Agentspace Project ID for header
        }

        new_agent_config_payload = {
            "id": agent_id,
            "displayName": agent_display_name,
            "vertexAiSdkAgentConnectionInfo": {"reasoningEngine": agent_engine_resource_name},
            "toolDescription": agent_description,
            "icon": {"uri": agent_icon_uri if agent_icon_uri and agent_icon_uri != "n/a" else "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"},
        }

        logger.info(f"Fetching current configuration for assistant (Legacy): {default_assistant_name}...")
        get_response = requests.get(assistant_api_endpoint, headers=common_headers)
        existing_agent_configs = []
        try:
            get_response.raise_for_status()
            current_config = get_response.json()
            existing_agent_configs = current_config.get("agentConfigs", [])
            logger.info(f"Found {len(existing_agent_configs)} existing agent configuration(s) (Legacy).")
        except requests.exceptions.RequestException as e:
            if e.response is not None and e.response.status_code == 404:
                logger.info(f"Assistant '{default_assistant_name}' not found (Legacy). Will create it with the new agent.")
                existing_agent_configs = []
            else:
                error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
                logger.error(f"Error fetching current assistant config (Legacy): {error_detail}")
                raise ValueError(f"Error fetching current assistant config: {error_detail}") from e

        updated_configs = [cfg for cfg in existing_agent_configs if cfg.get("id") != agent_id]
        updated_configs.append(new_agent_config_payload)

        patch_payload = {"agentConfigs": updated_configs}
        patch_endpoint_with_mask = f"{assistant_api_endpoint}?updateMask=agent_configs"
        
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in common_headers.items()}
        logger.info(f"LEGACY_REGISTER_REQUEST:\nURL: {patch_endpoint_with_mask}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(patch_payload, indent=2)}")

        response = requests.patch(patch_endpoint_with_mask, headers=common_headers, data=json.dumps(patch_payload))
        response.raise_for_status()
        
        try:
            response_json = response.json()
            logger.info(f"LEGACY_REGISTER_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            logger.info(f"LEGACY_REGISTER_RESPONSE (Status {response.status_code}):\n{response.text if response.text else '(empty body)'}")

        logger.info("Successfully registered agent with Agentspace (Legacy).")
        return True, "Registration successful!"

    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
        msg = f"Agentspace registration API call failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during registration: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

# --- Deregistration Logic ---

async def fetch_registered_agents_for_deregister(
    as_project_id: str, as_project_number: Optional[str], # Use as_project_id and as_project_number
    agentspace_app: Optional[Dict[str, Any]],
    list_container: ui.column, fetch_button: ui.button, deregister_button: ui.button, page_state: dict,
    assistant_name: str = "default_assistant"
) -> None:
    """Fetches agents currently registered within an Agentspace assistant."""
    if not all([as_project_id, as_project_number, agentspace_app]):
        ui.notify("Missing Agentspace Project ID, Number, or selected Agentspace App.", type="warning")
        return
    
    logger.info(f"Fetching registered agents (Legacy) for deregister from Agentspace App: {agentspace_app.get('engine_id')} in project {as_project_id}, assistant: {assistant_name}")



    fetch_button.disable()
    deregister_button.disable()
    list_container.clear()
    page_state["deregister_registered_agents"] = []
    page_state["deregister_selection"] = {}
    ui.notify(f"Fetching registered agents from assistant '{assistant_name}'...", type="info", spinner=True)

    location = agentspace_app['location']
    app_id = agentspace_app['engine_id']

    hostname = f"{location}-discoveryengine.googleapis.com" if location != "global" else "discoveryengine.googleapis.com"
    assistant_api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_name}"

    try:
        def get_config_sync():
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            if not credentials.token:
                logger.error("Failed to refresh ADC token for fetching legacy registered agents.")
                raise ValueError("Failed to refresh ADC token.")
            headers = {"Authorization": f"Bearer {credentials.token}", "x-goog-user-project": as_project_id} # Use Agentspace Project ID
            log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
            logger.info(f"LEGACY_FETCH_REGISTERED_AGENTS_REQUEST:\nURL: {assistant_api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}")
            response = requests.get(assistant_api_endpoint, headers=headers)
            response.raise_for_status()
            logger.info(f"LEGACY_FETCH_REGISTERED_AGENTS_RESPONSE (Status {response.status_code}): {len(response.json().get('agentConfigs', []))} configs found.")
            return response.json().get("agentConfigs", [])

        agent_configs = await asyncio.to_thread(get_config_sync)
        page_state["deregister_registered_agents"] = agent_configs

        with list_container:
            if not agent_configs:
                ui.label("No agents found registered in this assistant.")
                logger.info(f"No legacy agents found registered in assistant '{assistant_name}'.")
                ui.notify("No registered agents found.", type="info")
            else:
                ui.label(f"Found {len(agent_configs)} registered agents:").classes("font-semibold")
                for cfg in agent_configs:
                    agent_id = cfg.get("id", "Unknown ID")
                    display_name = cfg.get("displayName", "N/A")
                    engine_link = cfg.get('vertexAiSdkAgentConnectionInfo', {}).get('reasoningEngine', 'N/A')
                    with ui.card().classes("w-full p-2 my-1"):
                        with ui.row().classes("items-center"):
                            checkbox = ui.checkbox().bind_value(page_state["deregister_selection"], agent_id).classes("mr-2")
                            checkbox.on('update:model-value', lambda: update_deregister_button_state(page_state, deregister_button))
                            with ui.column().classes("gap-0"):
                                ui.label(f"{display_name}").classes("font-medium")
                                ui.label(f"ID: {agent_id}").classes("text-xs text-gray-500")
                                ui.label(f"Engine: {engine_link.split('/')[-1]}").classes("text-xs text-gray-500")
                update_deregister_button_state(page_state, deregister_button)
                logger.info(f"Successfully fetched {len(agent_configs)} legacy registered agents.")
                ui.notify(f"Successfully fetched {len(agent_configs)} registered agents.", type="positive")

    except requests.exceptions.RequestException as e:
        if e.response is not None and e.response.status_code == 404:
            msg = f"Assistant '{assistant_name}' not found in Agentspace App '{app_id}'."
            logger.warning(msg)
            with list_container: ui.label(msg)
            ui.notify(msg, type="warning")
        else:
            error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
            msg = f"API Error fetching assistant config: {error_detail}"
            logger.error(msg)
            with list_container: ui.label(msg).classes("text-red-500")
            ui.notify(msg, type="negative", multi_line=True, close_button=True)
    except Exception as e:
        msg = f"An unexpected error occurred: {e}"
        with list_container: ui.label(msg).classes("text-red-500")
        logger.error(f"Fetch legacy registered agents error: {msg}\n{traceback.format_exc()}")
        ui.notify(msg, type="negative", multi_line=True, close_button=True)
    finally:
        fetch_button.enable()

def deregister_agents_sync(
    as_project_id: str, as_project_number: str, # Use as_project_id and as_project_number
    agentspace_app: Dict[str, Any],
    agent_ids_to_remove: List[str], current_configs: List[Dict[str, Any]],
    assistant_name: str = "default_assistant"
) -> Tuple[bool, str]:
    """Synchronous function to deregister agents by patching the assistant."""
    logger.info(f"\n--- Deregistering {len(agent_ids_to_remove)} Agent(s) (Legacy Sync Call) ---")
    logger.info(f"Agentspace Project: {as_project_id} (Number: {as_project_number})")
    logger.info(f"Agentspace App: {agentspace_app['engine_id']} (Location: {agentspace_app['location']})")
    logger.info(f"Agent IDs to remove: {agent_ids_to_remove}")
    location = agentspace_app['location']
    app_id = agentspace_app['engine_id']

    hostname = f"{location}-discoveryengine.googleapis.com" if location != "global" else "discoveryengine.googleapis.com"
    patch_endpoint_with_mask = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_name}?updateMask=agent_configs"

    updated_configs = [cfg for cfg in current_configs if cfg.get("id") not in agent_ids_to_remove]
    payload = {"agentConfigs": updated_configs}

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh ADC token for legacy deregistration.")
            raise ValueError("Failed to refresh ADC token.")

        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
            "x-goog-user-project": as_project_id, # Use Agentspace Project ID
        }

        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.info(f"LEGACY_DEREGISTER_REQUEST:\nURL: {patch_endpoint_with_mask}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(payload, indent=2)}")

        response = requests.patch(patch_endpoint_with_mask, headers=headers, data=json.dumps(payload))
        response.raise_for_status()

        try:
            response_json = response.json()
            logger.info(f"LEGACY_DEREGISTER_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            logger.info(f"LEGACY_DEREGISTER_RESPONSE (Status {response.status_code}):\n{response.text if response.text else '(empty body)'}")

        logger.info(f"Successfully updated Agentspace assistant configuration (Legacy Deregistration). Removed {len(agent_ids_to_remove)} agent(s).")
        return True, f"Successfully deregistered {len(agent_ids_to_remove)} agent(s)."

    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
        msg = f"API Error during deregistration: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during deregistration: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

# --- NiceGUI Page Setup ---
@ui.page("/")
async def main_page(client: Client):
    """Main NiceGUI page combining Deploy and Destroy."""

    page_state = {
        "selected_agent_key": None, "selected_agent_config": None, "deploy_radio_group": None,
        "agent_cards": {}, "previous_selected_card": None,
        "destroy_agents": [], "destroy_selected": {}, # Deploy/Destroy
        "register_agent_engines": [], "register_agentspaces": [], "project_number": None, # Common for Register/Deregister
        "deregister_agentspaces": [], "deregister_registered_adk_agents": [], "deregister_selection": {}, # For Deregister Tab
        "selected_deregister_as_app": None, # For Deregister Tab
        'register_authorizations_list': [], # For Register Tab
        "project_id_input_timer": None, # For debouncing as_project_input
        # --- State for Test Tab ---
        "test_username": "test-user", # Default username for test tab
        "test_available_agents": [],
        "test_selected_agent_resource_name": None,
        "test_remote_agent_instance": None,
        "test_chat_session_id": None,
        "test_is_chatting": False,
    }

    ui.query('body').classes(add='text-base')
    header = ui.header(elevated=True).classes("items-center justify-between")
    with header:
        # Display the application title and version
        ui.label(f"ADK on Agent Engine: Lifecycle Manager v{__version__}").classes("text-2xl font-bold")

    if IMPORT_ERROR_MESSAGE:
        with ui.card().classes("w-full bg-red-100 dark:bg-red-900"):
            ui.label("Configuration Error").classes("text-xl font-bold text-red-700 dark:text-red-300")
            ui.label(IMPORT_ERROR_MESSAGE).classes("text-red-600 dark:text-red-400")
            logger.critical(f"Import error encountered: {IMPORT_ERROR_MESSAGE}")
        return

    with ui.right_drawer(top_corner=True, bottom_corner=True).classes("bg-gray-100 dark:bg-gray-800 p-4 flex flex-col").props("bordered") as right_drawer:
        ui.label("Configuration").classes("text-xl font-semibold mb-4")
        with ui.column().classes("gap-4 w-full grow"):
            with ui.card().classes("w-full p-4"):
                ui.label("GCP Project Settings").classes("text-lg font-semibold mb-2")
                common_project_default = os.getenv("GOOGLE_CLOUD_PROJECT", "")
                ae_project_input = ui.input(
                    "Agent Engine GCP Project ID",
                    value=os.getenv("AGENTENGINE_GCP_PROJECT", common_project_default)
                ).props("outlined dense").classes('w-full text-base').tooltip("Project ID for deploying and managing Agent Engines.")
                
                as_project_input = ui.input(
                    "Agentspace GCP Project ID",
                    value=os.getenv("AGENTSPACE_GCP_PROJECT", common_project_default)
                ).props("outlined dense").classes('w-full text-base').tooltip("Project ID for the Agentspace (Discovery Engine App) to register/deregister agents.")

                ui.label("Location Settings").classes("text-lg font-semibold mt-3 mb-2")
                location_select = ui.select(SUPPORTED_REGIONS, label="Agent Engine GCP Location", value=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")).props("outlined dense").classes('w-full text-base')
                agentspace_locations_options = ["global", "us", "eu"] # Multi-select for Agentspace locations
                default_agentspace_locations = os.getenv("AGENTSPACE_LOCATIONS", "global,us").split(',') # Use new env var
                agentspace_locations_select = ui.select(agentspace_locations_options, label="Agentspace Locations (for App Lookup)", multiple=True, value=default_agentspace_locations).props("outlined dense").classes('w-full text-base')
                bucket_input = ui.input("GCS Staging Bucket (Deploy)", value=os.getenv("AGENTENGINE_STAGING_BUCKET", "")).props("outlined dense prefix=gs://").classes('w-full text-base')
            
            ui.element('div').classes('grow')
            ui.html("Created by Aaron Lind<br>avlind@google.com").classes("text-xs text-gray-500 dark:text-gray-400")

    with header:
        ui.button(on_click=lambda: right_drawer.toggle(), icon='menu').props('flat color=white').classes('ml-auto')

    with ui.tabs().classes('w-full') as tabs:
        deploy_tab = ui.tab('Deploy', icon='rocket_launch')
        test_tab = ui.tab('Test', icon='chat') # New Test Tab
        destroy_tab = ui.tab('Destroy', icon='delete_forever')
        agentspace_auth_tab = ui.tab('Manage AuthN', icon='admin_panel_settings')
        register_tab = ui.tab('Register', icon='assignment')
        deregister_tab = ui.tab('Deregister', icon='assignment_return')


    with ui.tab_panels(tabs, value=deploy_tab).classes('w-full'):
        # --- Deploy Tab Panel ---
        with ui.tab_panel(deploy_tab):
            with ui.column().classes("w-full p-4 gap-4"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("Select Agent Configuration to Deploy").classes("text-xl font-semibold")
                    info_icon = ui.icon("info", color="primary").classes("cursor-pointer text-lg")
                    with ui.dialog() as info_dialog, ui.card():
                        ui.label(WEBUI_AGENTDEPLOYMENT_HELPTEXT)
                        ui.button("Close", on_click=info_dialog.close).classes("mt-4")
                    info_icon.on("click", info_dialog.open)

                deploy_agent_selection_area = ui.grid(columns=2).classes("w-full gap-2")
                deploy_button = ui.button("Deploy Agent", icon="cloud_upload", on_click=lambda: start_deployment())
                deploy_button.disable()
                deploy_status_area = ui.column().classes("w-full mt-2 p-4 border rounded-lg bg-gray-50 dark:bg-gray-900")
                with deploy_status_area:
                    ui.label("Configure deployment and select an agent.").classes("text-gray-500")
        
        # --- Test Tab Panel (New) ---
        with ui.tab_panel(test_tab):
            with ui.column().classes("w-full p-4 gap-4 items-stretch"):
                with ui.row().classes("items-center gap-2"): # Row for label and icon
                    ui.label("Test Deployed Agent Engines").classes("text-xl font-semibold")
                    test_info_icon = ui.icon("info", color="primary").classes("cursor-pointer text-lg")
                    with ui.dialog() as test_info_dialog, ui.card():
                        ui.label("ADK Agent Engine Testing Information").classes("text-lg font-semibold mb-2")
                        ui.markdown("This is a simple testing page for your deployed Agent Engine ADK-powered Agents. This UI only supports text-in and text-out, and will not show any detailed session events such as tools calling or agent transfers. For detailed debugging of ADK agents, please use the ADK provided `adk web` in your local environment.")
                        ui.button("Close", on_click=test_info_dialog.close).classes("mt-4")
                    test_info_icon.on("click", test_info_dialog.open)

                # Agent Selection for Test Tab
                with ui.card().classes("w-full p-4"):
                    ui.label("1. Select Agent Engine to Test").classes("text-lg font-semibold")
                    with ui.row().classes("w-full items-center gap-2"):
                        test_fetch_agents_button = ui.button("Fetch Deployed Agents", icon="refresh")
                        test_agent_select = ui.select(
                            options={},
                            label="Choose Agent Engine",
                            with_input=True,
                            on_change=lambda e: handle_test_agent_selection(e.value)
                        ).props("outlined dense").classes("flex-grow")
                        test_agent_select.set_visibility(False)

                # Username for Test Tab
                with ui.card().classes("w-full p-4"):
                    ui.label("2. Set Username (for UI identification in test chat)").classes("text-lg font-semibold")
                    test_username_input = ui.input(
                        "Username",
                        value=page_state["test_username"],
                        on_change=lambda e: page_state.update({"test_username": e.value})
                    ).props("outlined dense").classes("w-full")

                # Chat Area for Test Tab
                with ui.card().classes("w-full p-4 flex flex-col grow min-h-[300px]"):
                    ui.label("3. Chat with Agent").classes("text-lg font-semibold mb-2")
                    test_chat_messages_area = ui.column().classes("w-full overflow-y-auto h-full")
                    with test_chat_messages_area:
                        ui.label("Select an agent and set username to begin testing.").classes("text-gray-500")

                # Message Input for Test Tab
                with ui.card().classes("w-full p-4"):
                    with ui.row().classes("w-full items-center gap-2"):
                        test_message_input = ui.input(placeholder="Type your message to the agent...") \
                            .props('outlined dense clearable').classes('flex-grow') \
                            .on('keydown.enter', lambda: test_send_message_button.run_method('click'))
                        test_send_message_button = ui.button("Send", icon="send", on_click=lambda: handle_test_send_message())
                        test_send_message_button.disable() # Start disabled

            # --- Logic for Test Tab (Adapted from webui_remote_agent_test.py) ---
            async def fetch_agent_engines_for_test_chat():
                ae_project = ae_project_input.value
                ae_location = location_select.value
                if not ae_project or not ae_location:
                    ui.notify("Please set Agent Engine GCP Project ID and Location in the side configuration panel.", type="warning")
                    return

                test_agent_select.clear()
                test_agent_select.set_value(None)
                page_state["test_available_agents"] = []
                test_agent_select.set_visibility(False)
                await handle_test_agent_selection(None) # Reset agent specific state

                existing_agents, error_msg = await _fetch_vertex_ai_resources(
                    ae_project,
                    ae_location,
                    agent_engines.list,
                    ui_feedback_context={'button': test_fetch_agents_button, 'notify_prefix': "Agent Engines (Test)"}
                )

                if error_msg:
                    return # Error handled by _fetch_vertex_ai_resources

                if existing_agents is not None:
                    page_state["test_available_agents"] = existing_agents
                    if not existing_agents:
                        ui.notify("No deployed Agent Engines found for testing.", type="info")
                        test_agent_select.set_options([])
                    else:
                        options = {
                            agent.resource_name: f"{agent.display_name} ({agent.resource_name.split('/')[-1]})"
                            for agent in existing_agents
                        }
                        test_agent_select.set_options(options)
                        ui.notify(f"Found {len(existing_agents)} Agent Engines for testing.", type="positive")
                    test_agent_select.set_visibility(True)

            test_fetch_agents_button.on_click(fetch_agent_engines_for_test_chat)

            async def handle_test_agent_selection(resource_name: Optional[str]):
                logger.info(f"Test Agent selected via UI: {resource_name}")
                page_state["test_selected_agent_resource_name"] = resource_name
                page_state["test_remote_agent_instance"] = None
                page_state["test_chat_session_id"] = None
                with test_chat_messages_area: test_chat_messages_area.clear()
                if resource_name:
                    selected_agent_display_name = test_agent_select.options.get(resource_name, resource_name.split('/')[-1] if resource_name else "Agent")
                    ui.notify(f"Test Agent '{selected_agent_display_name}' selected. Ready to chat.", type="info")
                    test_send_message_button.set_enabled(not page_state['test_is_chatting'])
                else:
                    test_send_message_button.set_enabled(False)

        # --- Destroy Tab Panel ---
        with ui.tab_panel(destroy_tab):
            with ui.column().classes("w-full p-4 gap-4"):
                fetch_destroy_button = ui.button("Fetch Existing Agent Engines", icon="refresh",
                                                 on_click=lambda: fetch_agents_for_destroy(
                                                     ae_project_input.value, location_select.value, # Use ae_project_input
                                                     destroy_list_container, destroy_delete_button, fetch_destroy_button,
                                                     page_state))
                with ui.card().classes("w-full mt-2"):
                    ui.label("Your Agent Engines").classes("text-lg font-semibold")
                    destroy_list_container = ui.column().classes("w-full")
                    with destroy_list_container:
                        ui.label("Click 'Fetch Existing Agent Engines'.").classes("text-gray-500")
                with ui.row().classes("w-full mt-4 justify-end"):
                    destroy_delete_button = ui.button("Delete Selected Agents", color="red", icon="delete_forever",
                                                      on_click=lambda: confirm_and_delete_agents(
                                                          ae_project_input.value, location_select.value, page_state)) # Use ae_project_input
                    destroy_delete_button.disable()

        # --- Register (V2) Tab Panel ---
        with ui.tab_panel(register_tab):
            with ui.column().classes("w-full p-4 gap-4"):
                ui.label("Register Agent Engine with Agentspace").classes("text-xl font-semibold")
                with ui.stepper().props('vertical flat').classes('w-full') as stepper_register:
                    with ui.step("Select Agent Engine"):
                        ui.label("Choose the deployed Agent Engine to register.")
                        register_fetch_ae_button = ui.button("Fetch Agent Engines", icon="refresh")
                        register_ae_select = ui.select(options={}, label="Agent Engine").props("outlined dense").classes("w-full mt-2")
                        register_ae_select.set_visibility(False)
                        with ui.stepper_navigation():
                            register_next_button_step1 = ui.button("Next", on_click=stepper_register.next)
                            register_next_button_step1.bind_enabled_from(register_ae_select, 'value')
                        register_fetch_ae_button.on_click(lambda: fetch_agent_engines_for_register(
                            ae_project_input.value, location_select.value, # Use ae_project_input
                            register_ae_select, register_fetch_ae_button, page_state, register_next_button_step1))

                    with ui.step("Select Agentspace App"):
                        ui.label("Choose the Agentspace App (Discovery Engine App ID).")
                        register_fetch_as_button = ui.button("Fetch Agentspace Apps", icon="refresh")
                        register_as_select = ui.select(options={}, label="Agentspace App").props("outlined dense").classes("w-full mt-2")
                        register_as_select.set_visibility(False)
                        with ui.stepper_navigation():
                            ui.button("Back", on_click=stepper_register.previous, color='gray')
                            register_next_button_step2 = ui.button("Next", on_click=stepper_register.next)
                            register_next_button_step2.bind_enabled_from(register_as_select, 'value')
                        register_fetch_as_button.on_click(lambda: fetch_agentspace_apps(
                            as_project_input.value, agentspace_locations_select.value, # Use as_project_input
                            register_as_select, register_fetch_as_button, page_state, 'register_agentspaces',
                            register_next_button_step2))

                    with ui.step("Configure & Register"):
                        ui.label("Provide details for the new agent registration.").classes("font-semibold")
                        register_display_name_input = ui.input("Display Name").props("outlined dense").classes("w-full")
                        register_description_input = ui.textarea("Description (General)").props("outlined dense").classes("w-full")
                        register_tool_description_input = ui.textarea("Tool Description (Prompt for LLM)").props("outlined dense").classes("w-full")
                        register_icon_input = ui.input("Icon URI (optional)", value="https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg").props("outlined dense").classes("w-full")
                        
                        ui.label("Authorizations (Optional)").classes("text-md font-medium mt-3 mb-1")
                        ui.label("Add full resource names for each OAuth 2.0 authorization required by the agent.").classes("text-xs text-gray-500 mb-2")
                        direct_auth_inputs_container = ui.column().classes("w-full gap-1")

                        @ui.refreshable
                        def render_register_auth_inputs(): # Renamed for clarity
                            direct_auth_inputs_container.clear()
                            current_auths = page_state.get('register_authorizations_list', [])
                            with direct_auth_inputs_container:
                                if not current_auths:
                                    ui.label("No authorizations added yet.").classes("text-xs text-gray-400")
                                for i, auth_value in enumerate(current_auths):
                                    with ui.row().classes("w-full items-center no-wrap"):
                                        ui.input(
                                            label=f"Auth #{i+1}", value=auth_value,
                                            placeholder="projects/PROJECT_ID/locations/global/authorizations/AUTH_ID",
                                            on_change=lambda e, index=i: page_state['register_authorizations_list'].__setitem__(index, e.value)
                                        ).props("outlined dense clearable").classes("flex-grow")
                                        ui.button(icon="remove_circle_outline", on_click=lambda _, index=i: (
                                            page_state['register_authorizations_list'].pop(index),
                                            render_register_auth_inputs.refresh()
                                        )).props("flat color=negative dense").tooltip("Remove this authorization")
                        render_register_auth_inputs()
                        ui.button("Add Authorization", icon="add", on_click=lambda: (
                            page_state.setdefault('register_authorizations_list', []).append(""),
                            render_register_auth_inputs.refresh()
                        )).classes("mt-2 self-start")

                        async def update_register_defaults():
                            selected_ae_resource = register_ae_select.value
                            selected_ae = next((ae for ae in page_state.get("register_agent_engines", []) if ae.resource_name == selected_ae_resource), None)
                            if selected_ae:
                                config_match = next((cfg for cfg_key, cfg in AGENT_CONFIGS.items() if isinstance(cfg, dict) and cfg.get("ae_display_name") == selected_ae.display_name), None)
                                if config_match:
                                    register_display_name_input.value = config_match.get("as_display_name", selected_ae.display_name)
                                    default_desc = config_match.get("description", f"Agent: {selected_ae.display_name}")
                                    register_description_input.value = default_desc
                                    register_tool_description_input.value = config_match.get("as_tool_description", default_desc)
                                    register_icon_input.value = config_match.get("as_uri", "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg")
                                else:
                                    register_display_name_input.value = selected_ae.display_name
                                    default_desc = f"Agent: {selected_ae.display_name}"
                                    register_description_input.value = default_desc
                                    register_tool_description_input.value = default_desc
                                    register_icon_input.value = "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"
                            page_state['register_authorizations_list'] = []
                            render_register_auth_inputs.refresh()
                        
                        ui.timer(0.1, update_register_defaults, once=True)
                        register_ae_select.on('update:model-value', update_register_defaults)

                        register_button = ui.button("Register Agent", icon="app_registration", on_click=lambda: start_registration())
                        register_status_area = ui.column().classes("w-full mt-2 p-2 border rounded bg-gray-50 dark:bg-gray-900 min-h-[50px]")
                        with register_status_area: ui.label("Ready for registration.").classes("text-sm text-gray-500")
                        with ui.stepper_navigation():
                            ui.button("Back", on_click=stepper_register.previous, color='gray')

        # --- Deregister (V2) Tab Panel ---
        with ui.tab_panel(deregister_tab):
            with ui.column().classes("w-full p-4 gap-4"):
                ui.label("Deregister ADK Agent from Agentspace").classes("text-xl font-semibold")
                deregister_fetch_as_button = ui.button("Fetch Agentspace Apps", icon="refresh")
                deregister_as_select = ui.select(options={}, label="Select Agentspace App").props("outlined dense").classes("w-full mt-2")
                deregister_as_select.set_visibility(False)
                deregister_fetch_as_button.on_click(lambda: fetch_agentspace_apps(
                    as_project_input.value, agentspace_locations_select.value, # Use as_project_input
                    deregister_as_select, deregister_fetch_as_button, page_state, 'deregister_agentspaces'))

                with ui.card().classes("w-full mt-2"):
                    ui.label("Registered ADK Agents in Selected App").classes("text-lg font-semibold")
                    with ui.row().classes("items-center gap-2 mb-2"):
                        async def _handle_fetch_registered_agents():
                            """Async handler to ensure state is updated before fetching agents."""
                            # Similar to legacy, ensure project number is up-to-date.
                            if page_state.get("project_id_input_timer") and not page_state["project_id_input_timer"].active:
                                page_state["project_id_input_timer"] = None

                            if not page_state.get("project_id_input_timer"):
                                await _perform_project_number_update()

                            # Now call the main fetch function with potentially updated state
                            await fetch_registered_agents_async(
                                as_project_id=as_project_input.value,
                                as_project_number=page_state.get('project_number'),
                                agentspace_app=page_state.get('selected_deregister_as_app'), # type: ignore
                                list_container=deregister_list_container,
                                fetch_button=deregister_fetch_reg_button,
                                deregister_button=deregister_button,
                                page_state=page_state
                            )
                        deregister_fetch_reg_button = ui.button(
                            "Fetch Registered ADK Agents",
                            icon="refresh",
                            on_click=_handle_fetch_registered_agents
                        )
                        deregister_fetch_reg_button.bind_enabled_from(deregister_as_select, 'value', backward=lambda x: bool(x))
                    deregister_list_container = ui.column().classes("w-full")
                    with deregister_list_container: ui.label("Select an Agentspace App and click 'Fetch Registered ADK Agents'.").classes("text-gray-500")
                with ui.row().classes("w-full mt-4 justify-end"):
                    deregister_button = ui.button("Deregister Selected Agents", color="red", icon="delete",
                                                  on_click=lambda: confirm_and_deregister())
                    deregister_button.disable()
                deregister_status_area = ui.column().classes("w-full mt-2 p-2 border rounded bg-gray-50 dark:bg-gray-900 min-h-[50px]")
                with deregister_status_area: ui.label("Ready for deregistration.").classes("text-sm text-gray-500")

        # --- Agentspace Authorization Management Tab Panel (New) ---
        with ui.tab_panel(agentspace_auth_tab):
            with ui.column().classes("w-full p-4 gap-4"):
                ui.label("Manage Agentspace OAuth Authentications").classes("text-xl font-semibold") # Renamed title
                ui.label(f"Authorizations are managed at the '{AS_AUTH_DEFAULT_LOCATION}' location.").classes("text-sm text-gray-500 mb-3")

                with ui.tabs().classes('w-full') as auth_sub_tabs:
                    auth_create_tab_btn = ui.tab('Create Authorization', icon='add_circle_outline')
                    auth_delete_tab_btn = ui.tab('Delete Authorization', icon='delete_outline')

                with ui.tab_panels(auth_sub_tabs, value=auth_create_tab_btn).classes('w-full mt-4'):
                    with ui.tab_panel(auth_create_tab_btn):
                        with ui.column().classes("w-full gap-3"):
                            # Define UI elements first
                            auth_id_create_input_el = ui.input("Authorization ID", placeholder="e.g., my-google-oauth-client").props("outlined dense clearable").classes("w-full")
                            auth_client_id_input_el = ui.input("OAuth Client ID").props("outlined dense clearable").classes("w-full")
                            auth_client_secret_input_el = ui.input("OAuth Client Secret", password=True, password_toggle_button=True).props("outlined dense clearable").classes("w-full")
                            auth_uri_input_el = ui.input("OAuth Authorization URI", placeholder="https://accounts.google.com/o/oauth2/v2/auth").props("outlined dense clearable").classes("w-full")
                            auth_token_uri_input_el = ui.input("OAuth Token URI", placeholder="https://oauth2.googleapis.com/token").props("outlined dense clearable").classes("w-full")
                            auth_create_status_area = ui.column().classes("w-full mt-3 p-3 border rounded bg-gray-50 dark:bg-gray-800 min-h-[60px]")
                            with auth_create_status_area: ui.label("Fill in details and click 'Create Authorization'.").classes("text-sm text-gray-500")
                            auth_create_button_el = ui.button("Create Authorization", icon="save")

                            # Define handler for Create Authorization
                            async def _handle_create_authorization():
                                target_project_id = as_project_input.value # Use Agentspace Project ID for this
                                auth_id = auth_id_create_input_el.value
                                client_id = auth_client_id_input_el.value
                                client_secret = auth_client_secret_input_el.value
                                auth_uri = auth_uri_input_el.value
                                token_uri = auth_token_uri_input_el.value

                                if not all([target_project_id, auth_id, client_id, client_secret, auth_uri, token_uri]):
                                    ui.notify("All fields are required for authorization creation. Please check inputs.", type="warning")
                                    return

                                auth_create_button_el.disable()
                                with auth_create_status_area:
                                    auth_create_status_area.clear()
                                    with ui.row().classes("items-center"):
                                        ui.spinner(size="lg").classes("mr-2")
                                        ui.label("Attempting to create authorization...")

                                access_token, _, token_error = await get_access_token_and_credentials_async_webui()
                                if token_error or not access_token:
                                    with auth_create_status_area:
                                        auth_create_status_area.clear()
                                        ui.label(f"Error getting access token: {token_error or 'Unknown error'}").classes("text-red-600")
                                    ui.notify(f"Access Token Error: {token_error or 'Unknown error'}", type="negative", multi_line=True)
                                    auth_create_button_el.enable()
                                    return

                                target_project_number = await get_project_number(target_project_id)
                                if not target_project_number:
                                    with auth_create_status_area:
                                        auth_create_status_area.clear()
                                        ui.label(f"Error getting project number for {target_project_id}.").classes("text-red-600")
                                    ui.notify(f"Project Number Error for {target_project_id}.", type="negative", multi_line=True)
                                    auth_create_button_el.enable()
                                    return

                                success, message = await asyncio.to_thread(
                                    create_authorization_sync_webui,
                                    target_project_id, target_project_number, auth_id, client_id, client_secret, auth_uri, token_uri, access_token
                                )

                                with auth_create_status_area:
                                    auth_create_status_area.clear()
                                    if success:
                                        ui.html(f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                                        ui.notify("Authorization created successfully!", type="positive", multi_line=True)
                                        auth_id_create_input_el.set_value("")
                                        auth_client_id_input_el.set_value("")
                                        auth_client_secret_input_el.set_value("")
                                        auth_uri_input_el.set_value("")
                                        auth_token_uri_input_el.set_value("")
                                    else:
                                        ui.html(f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                                        ui.notify("Failed to create authorization.", type="negative", multi_line=True)
                                auth_create_button_el.enable()

                            # Assign handler to button
                            auth_create_button_el.on_click(_handle_create_authorization)

                    with ui.tab_panel(auth_delete_tab_btn):
                        with ui.column().classes("w-full gap-3"):
                            # Define UI elements first
                            auth_id_delete_input_el = ui.input("Authorization ID to Delete", placeholder="e.g., my-google-oauth-client").props("outlined dense clearable").classes("w-full")
                            auth_delete_status_area = ui.column().classes("w-full mt-3 p-3 border rounded bg-gray-50 dark:bg-gray-800 min-h-[60px]")
                            with auth_delete_status_area: ui.label("Enter Authorization ID and click 'Delete Authorization'.").classes("text-sm text-gray-500")
                            auth_delete_button_el = ui.button("Delete Authorization", icon="delete_forever", color="red")

                            # Define handler for Delete Authorization (including nested helper)
                            async def _run_actual_auth_deletion_webui(target_project_id: str, auth_id: str):
                                auth_delete_button_el.disable()
                                with auth_delete_status_area:
                                    auth_delete_status_area.clear()
                                    with ui.row().classes("items-center"): ui.spinner(size="lg").classes("mr-2"); ui.label(f"Attempting to delete '{auth_id}'...")

                                access_token, _, token_error = await get_access_token_and_credentials_async_webui()
                                if token_error or not access_token:
                                    with auth_delete_status_area: auth_delete_status_area.clear(); ui.label(f"Token Error: {token_error or 'Unknown'}").classes("text-red-600")
                                    ui.notify(f"Access Token Error: {token_error or 'Unknown'}", type="negative"); auth_delete_button_el.enable(); return

                                target_project_number = await get_project_number(target_project_id)
                                if not target_project_number:
                                    with auth_delete_status_area: auth_delete_status_area.clear(); ui.label(f"Project Number Error for {target_project_id}.").classes("text-red-600")
                                    ui.notify(f"Project Number Error for {target_project_id}.", type="negative"); auth_delete_button_el.enable(); return

                                success, message = await asyncio.to_thread(delete_authorization_sync_webui, target_project_id, target_project_number, auth_id, access_token)
                                with auth_delete_status_area:
                                    auth_delete_status_area.clear()
                                    if success: ui.html(f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>"); ui.notify("Authorization deleted!", type="positive"); auth_id_delete_input_el.set_value("")
                                    else: ui.html(f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>"); ui.notify("Deletion failed.", type="negative", multi_line=True)
                                auth_delete_button_el.enable()

                            async def _handle_delete_authorization():
                                target_project_id = as_project_input.value # Use Agentspace Project ID
                                auth_id = auth_id_delete_input_el.value

                                if not all([target_project_id, auth_id]):
                                    ui.notify("Agentspace Project ID and Authorization ID are required for deletion.", type="warning")
                                    return

                                with ui.dialog() as confirm_dialog, ui.card():
                                    ui.label(f"Are you sure you want to delete authorization '{auth_id}' from project '{target_project_id}'?").classes("text-lg mb-2")
                                    ui.label("This action cannot be undone.").classes("font-semibold text-red-600")
                                    with ui.row().classes("mt-5 w-full justify-end gap-2"):
                                        ui.button("Cancel", on_click=confirm_dialog.close, color="gray")
                                        ui.button("Delete Permanently",
                                                  on_click=lambda: (confirm_dialog.close(), asyncio.create_task(_run_actual_auth_deletion_webui(target_project_id, auth_id))),
                                                  color="red")
                                await confirm_dialog
                            
                            # Assign handler to button
                            auth_delete_button_el.on_click(_handle_delete_authorization)

    # --- Logic for Deploy Tab ---
    def handle_deploy_agent_selection(agent_key: str):
        nonlocal page_state
        if not all([ae_project_input.value, location_select.value, bucket_input.value]): # Use ae_project_input
             ui.notify("Please configure Agent Engine Project, Location, and Bucket in the side panel first.", type="warning")
             if page_state["deploy_radio_group"]: page_state["deploy_radio_group"].set_value(None)
             return

        if page_state["previous_selected_card"]:
            page_state["previous_selected_card"].classes(remove='border-blue-500 dark:border-blue-400')

        page_state["selected_agent_key"] = agent_key
        page_state["selected_agent_config"] = AGENT_CONFIGS.get(agent_key)

        current_card = page_state["agent_cards"].get(agent_key)
        if current_card:
            current_card.classes(add='border-blue-500 dark:border-blue-400')
            page_state["previous_selected_card"] = current_card

        logger.debug(f"Selected agent for deploy: {agent_key}")
        update_deploy_button_state()

    def update_deploy_button_state():
        core_config_ok = ae_project_input.value and location_select.value and bucket_input.value # Use ae_project_input
        agent_config_selected = page_state["selected_agent_key"] is not None
        if core_config_ok and agent_config_selected:
            deploy_button.enable()
        else:
            deploy_button.disable()

    with deploy_agent_selection_area:
        if not AGENT_CONFIGS or "error" in AGENT_CONFIGS:
            ui.label("No agent configurations found or error loading them.").classes("text-red-500")
        else:
            page_state["deploy_radio_group"] = ui.radio(
                [key for key in AGENT_CONFIGS.keys()],
                on_change=lambda e: handle_deploy_agent_selection(e.value)
            ).props("hidden")

            for key, config in AGENT_CONFIGS.items():
                card = ui.card().classes("w-full p-3 cursor-pointer hover:shadow-md border-2 border-transparent")
                page_state["agent_cards"][key] = card
                with card.on('click', lambda k=key: page_state["deploy_radio_group"].set_value(k)):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(f"{config.get('ae_display_name', key)}").classes("text-lg font-medium")
                    with ui.column().classes("gap-0 mt-1 text-sm text-gray-600 dark:text-gray-400"):
                        ui.label(f"Config Key: {key}")
                        ui.label(f"Engine Name: {config.get('ae_display_name', 'N/A')}")
                        ui.label(f"Description: {config.get('description', 'N/A')}")
                        ui.label(f"Module: {config.get('module_path', 'N/A')}:{config.get('root_variable', 'N/A')}")

    async def start_deployment():
        ae_project = ae_project_input.value # Use Agent Engine Project ID
        location = location_select.value
        bucket = bucket_input.value
        agent_key = page_state["selected_agent_key"]
        agent_config = page_state["selected_agent_config"]

        if not all([ae_project, location, bucket, agent_key]):
            ui.notify("Please provide Agent Engine Project ID, Location, Bucket, and select an Agent.", type="warning")
            return
        if not agent_config:
            ui.notify("Internal Error: No agent configuration selected.", type="negative")
            return

        with ui.dialog() as confirm_dialog, ui.card():
            ui.label("Confirm Agent Deployment").classes("text-xl font-bold")
            with ui.column().classes("gap-1 mt-2"):
                ui.label("Agent Engine Project:").classes("font-semibold"); ui.label(f"{ae_project}")
                ui.label("Location:").classes("font-semibold"); ui.label(f"{location}")
                ui.label("Bucket:").classes("font-semibold"); ui.label(f"gs://{bucket}")
                ui.label("Agent Config Key:").classes("font-semibold"); ui.label(f"{agent_key}")

            default_display_name = agent_config.get("ae_display_name", f"{agent_key.replace('_', ' ').title()} Agent")
            logger.info(f"Confirming deployment for agent: {agent_key}, AE Project: {ae_project}, Location: {location}, Bucket: {bucket}, Display Name: {default_display_name}")
            default_description = agent_config.get("description", f"Agent: {agent_key}")
            display_name_input = ui.input("Agent Engine Name", value=default_display_name).props("outlined dense").classes("w-full mt-3")
            description_input = ui.textarea("Description", value=default_description).props("outlined dense").classes("w-full mt-2")

            ui.label("Proceed with deployment?").classes("mt-4")
            with ui.row().classes("mt-4 w-full justify-end"):
                ui.button("Cancel", on_click=confirm_dialog.close, color="gray")
                ui.button("Deploy", on_click=lambda: (
                    confirm_dialog.close(),
                    asyncio.create_task(run_deployment_async(
                        ae_project, location, bucket, agent_key, agent_config,
                        display_name_input.value, description_input.value,
                        deploy_button, deploy_status_area
                    ))
                ))
        await confirm_dialog

    # --- Logic for Test Tab Chat (Adapted from webui_remote_agent_test.py) ---
    async def handle_test_send_message():
        user_message_text = test_message_input.value
        if not user_message_text or not user_message_text.strip():
            ui.notify("Message cannot be empty for test chat.", type="warning")
            return

        if not page_state["test_selected_agent_resource_name"]:
            ui.notify("Please select an Agent Engine for testing first.", type="warning")
            return

        page_state["test_is_chatting"] = True
        test_send_message_button.set_enabled(False)

        with test_chat_messages_area:
            ui.chat_message(user_message_text, name=page_state["test_username"], sent=True)
        test_message_input.set_value(None)

        agent_display_name = "Agent"
        if page_state["test_selected_agent_resource_name"]:
            agent_display_name = test_agent_select.options.get(page_state["test_selected_agent_resource_name"], page_state["test_selected_agent_resource_name"].split('/')[-1])
        
        thinking_message_container = None
        with test_chat_messages_area:
            thinking_message_container = ui.chat_message(name=agent_display_name, stamp="typing...")

        try:
            current_ae_project = ae_project_input.value
            current_ae_location = location_select.value

            if not page_state["test_remote_agent_instance"] or not page_state["test_chat_session_id"]:
                logger.info(f"Initializing connection to test agent: {page_state['test_selected_agent_resource_name']}")
                
                # Use existing init_vertex_ai from webui_manager.py
                init_ok, init_msg = await asyncio.to_thread(init_vertex_ai, current_ae_project, current_ae_location)
                if not init_ok:
                    ui.notify(f"Failed to initialize Vertex AI for test: {init_msg}", type="negative")
                    if thinking_message_container: thinking_message_container.delete()
                    raise Exception(f"Vertex AI Init Failed for test: {init_msg}")

                def get_agent_sync_test():
                    return agent_engines.get(resource_name=page_state["test_selected_agent_resource_name"])
                
                remote_agent = await asyncio.to_thread(get_agent_sync_test)
                page_state["test_remote_agent_instance"] = remote_agent
                
                def create_session_sync_test():
                    if page_state["test_remote_agent_instance"]:
                        return page_state["test_remote_agent_instance"].create_session(user_id=page_state["test_username"])
                    raise Exception("Test remote agent instance became unavailable before session creation.")

                session_object = await asyncio.to_thread(create_session_sync_test)
                if isinstance(session_object, dict) and "id" in session_object:
                    page_state["test_chat_session_id"] = session_object["id"]
                    logger.info(f"Created new test session ID: {page_state['test_chat_session_id']} for agent {page_state['test_selected_agent_resource_name']}")
                else:
                    logger.error(f"Failed to extract test session ID from session object: {session_object}")
                    ui.notify(f"Error: Could not obtain a valid test session ID. Response: {str(session_object)[:200]}", type="negative", multi_line=True)
                    if thinking_message_container: thinking_message_container.delete()
                    raise Exception(f"Could not obtain valid test session ID. Response: {session_object}")
                ui.notify("Connected to test agent and session started.", type="positive")

            logger.info(f"Sending message to test agent: '{user_message_text}', session: {page_state['test_chat_session_id']}")
            
            def stream_and_aggregate_agent_response_sync_test():
                agent_instance = page_state["test_remote_agent_instance"]
                if not agent_instance: raise Exception("Test remote agent instance not available.")
                
                full_response_parts, all_events_received = [], []
                for event in agent_instance.stream_query(message=user_message_text, session_id=page_state["test_chat_session_id"], user_id=page_state["test_username"]):
                    all_events_received.append(event)
                    event_content = event.get("content")
                    if isinstance(event_content, dict) and event_content.get("role") == "model":
                        for part in event_content.get("parts", []):
                            if "text" in part and part["text"]: full_response_parts.append(part["text"])
                    elif event.get("role") == "model": # Fallback
                        for part in event.get("parts", []):
                            if "text" in part and part["text"]: full_response_parts.append(part["text"])
                if not full_response_parts:
                    logger.warning(f"Test agent stream_query no text parts. Events: {all_events_received}")
                    return "Agent did not return a textual response."
                return "".join(full_response_parts)

            agent_response_text = await asyncio.to_thread(stream_and_aggregate_agent_response_sync_test)
            logger.info(f"Aggregated test agent response: {agent_response_text}")
            if thinking_message_container: thinking_message_container.delete()
            with test_chat_messages_area: ui.chat_message(str(agent_response_text), name=agent_display_name, sent=False)
        except Exception as e:
            logger.error(f"Error during test chat: {e}\n{traceback.format_exc()}")
            ui.notify(f"Test Chat Error: {e}", type="negative", multi_line=True, close_button=True)
            if thinking_message_container:
                try: thinking_message_container.delete()
                except Exception as del_e: logger.warning(f"Could not delete test thinking message: {del_e}")
            with test_chat_messages_area: ui.chat_message(f"Error: {str(e)[:100]}...", name="System", sent=False, stamp="Error")
        finally:
            page_state["test_is_chatting"] = False
            test_send_message_button.set_enabled(bool(page_state["test_selected_agent_resource_name"]))

    # --- Logic for Register Tab ---
    async def start_registration():
        as_project = as_project_input.value # Agentspace Project ID
        as_project_num = await get_project_number(as_project) # Agentspace Project Number
        selected_ae_resource = register_ae_select.value
        selected_as_key = register_as_select.value
        
        display_name = register_display_name_input.value
        description = register_description_input.value
        tool_description = register_tool_description_input.value
        icon_uri = register_icon_input.value
        
        authorizations_list_from_state = page_state.get('register_authorizations_list', [])
        authorizations_list_for_api = [auth.strip() for auth in authorizations_list_from_state if auth and auth.strip()]
        
        if not all([as_project, as_project_num, selected_ae_resource, selected_as_key, display_name, description, tool_description]):
            ui.notify("Missing required fields for registration (Agentspace Project, Engine, App, names/desc). Please check inputs.", type="warning")
            return
        logger.info(f"Starting registration. AS Project: {as_project}, AE Resource: {selected_ae_resource}, AS App Key: {selected_as_key}, Display Name: {display_name}, Authorizations: {authorizations_list_for_api}")

        selected_as_app = next((app for app in page_state.get("register_agentspaces", [])
                                if f"{app['location']}/{app['engine_id']}" == selected_as_key), None)
        if not selected_as_app:
            ui.notify("Internal Error: Could not find selected Agentspace App details.", type="negative")
            return

        register_button.disable()
        with register_status_area:
            register_status_area.clear()
            ui.label("Registering agent...")
            ui.spinner()

        success, message = await asyncio.to_thread(
            register_agent_sync, # Updated function name
            as_project, as_project_num, selected_as_app,
            selected_ae_resource, display_name, description,
            tool_description, icon_uri, authorizations_list_for_api
        )

        with register_status_area:
            register_status_area.clear()
            if success:
                ui.html(f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                logger.info(f"Registration successful: {message}")
                ui.notify("Agent registered successfully!", type="positive", multi_line=True, close_button=True)
            else:
                error_summary = message.splitlines()[0] if message else 'Unknown error'
                ui.html(f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                logger.error(f"Registration failed: {message}")
                ui.notify(f"Failed to register agent: {error_summary}", type="negative", multi_line=True, close_button=True)
        register_button.enable()

    # --- Logic for Deregister Tabs (State Updates with Debouncing) ---
    async def _perform_project_number_update():
        """
        The actual logic to update project number and dependent UI.
        This is called by the debouncer or directly when needed.
        """
        project_id_val = as_project_input.value # type: ignore
        
        # If project_id_val is empty and project_number was previously set, reset.
        if not project_id_val:
            if page_state.get('project_number') is not None:
                logger.info("Agentspace project ID cleared. Resetting project number and dependent UI.")
                page_state['project_number'] = None
                page_state['_last_fetched_project_id_for_number'] = None # Reset cache key
                await update_deregister_app_selection()
            return

        # Avoid re-fetching if the project ID hasn't effectively changed and we already have a number.
        current_project_id_for_number = page_state.get("_last_fetched_project_id_for_number")
        if project_id_val == current_project_id_for_number and page_state.get('project_number') is not None:
            logger.debug(f"Project ID {project_id_val} hasn't changed and number is known. Skipping fetch of project number.")
            # Still need to update dependent selections as they might have changed independently
            await update_deregister_app_selection()
            return

        logger.info(f"Fetching project number for Agentspace GCP Project ID: {project_id_val}")
        page_state['project_number'] = await get_project_number(project_id_val) # type: ignore
        if page_state['project_number'] is not None:
            page_state['_last_fetched_project_id_for_number'] = project_id_val
        else:
            page_state['_last_fetched_project_id_for_number'] = None
        
        logger.info(f"Agentspace project number updated to: {page_state['project_number']} for project ID: {project_id_val}")
        
        await update_deregister_app_selection()

    async def _debounced_project_id_update_action():
        """Action to be called by the timer after debounce period."""
        await _perform_project_number_update()
        page_state["project_id_input_timer"] = None # Clear timer from state

    def handle_as_project_input_change():
        """Debounces the project number update when as_project_input changes."""
        if page_state.get("project_id_input_timer"):
            page_state["project_id_input_timer"].cancel() # type: ignore
        
        if as_project_input.value and as_project_input.value.strip(): # type: ignore
            page_state["project_id_input_timer"] = ui.timer(0.75, _debounced_project_id_update_action, once=True)
        else: # If input is cleared, trigger the update immediately.
            asyncio.create_task(_perform_project_number_update())
            page_state["project_id_input_timer"] = None # Ensure timer is cleared from state

    async def update_deregister_app_selection():
        """Updates state and UI for deregistration based on selected Agentspace App."""
        selected_as_key = deregister_as_select.value
        selected_as_app = next((app for app in page_state.get("deregister_agentspaces", [])
                                if f"{app['location']}/{app['engine_id']}" == selected_as_key), None)
        page_state['selected_deregister_as_app'] = selected_as_app
        logger.debug(f"Deregister selected Agentspace App: {selected_as_app}")
        deregister_list_container.clear()
        with deregister_list_container: ui.label("Select an Agentspace App and click 'Fetch Registered ADK Agents'.").classes("text-gray-500")
        page_state["deregister_registered_adk_agents"] = []
        page_state["deregister_selection"] = {}
        update_deregister_button_state(page_state, deregister_button)

    async def confirm_and_deregister():
        selected_resource_names = [name for name, selected in page_state.get("deregister_selection", {}).items() if selected]
        if not selected_resource_names:
            ui.notify("No ADK agents selected for deregistration.", type="warning")
            return
        logger.info(f"Confirming deregistration for agent resource names: {selected_resource_names}")

        as_project = as_project_input.value # Agentspace Project ID
        if not as_project or not page_state.get('project_number') or not page_state.get('selected_deregister_as_app'):
            ui.notify("Missing Agentspace Project or Agentspace App selection for deregistration.", type="warning")
            return

        with ui.dialog() as dialog, ui.card():
            ui.label("Confirm Deregistration").classes("text-xl font-bold")
            ui.label("Permanently remove the following ADK agent registrations?")
            for resource_name in selected_resource_names:
                agent_details = next((agent for agent in page_state.get("deregister_registered_adk_agents", []) if agent.get("name") == resource_name), None)
                display_name = agent_details.get("displayName", resource_name.split("/")[-1]) if agent_details else resource_name.split("/")[-1]
                ui.label(f"- {display_name} (Name: ...{resource_name[-20:]})")
            ui.label("This does NOT delete the underlying Agent Engine deployment.").classes("mt-2")
            with ui.row().classes("mt-4 w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close, color="gray")
                ui.button("Deregister", color="red", on_click=lambda: run_actual_deregistration(
                    as_project, selected_resource_names, dialog
                ))
        await dialog

    async def run_actual_deregistration(as_project, resource_names_to_delete, dialog): # as_project is Agentspace Project ID
        dialog.close()
        deregister_button.disable()
        with deregister_status_area:
            deregister_status_area.clear()
            ui.spinner()
            ui.label("Deregistering ADK agents...")
        logger.info(f"Running actual deregistration for agent resource names: {resource_names_to_delete}, AS Project: {as_project}")

        success_count = 0
        fail_count = 0
        for name in resource_names_to_delete:
            success, message = await asyncio.to_thread(deregister_agent_sync, as_project, name)
            if success:
                success_count += 1
                logger.info(f"Successfully deregistered {name.split('/')[-1]}. Message: {message}")
                ui.notify(f"Successfully deregistered {name.split('/')[-1]}.", type="positive")
            else:
                fail_count += 1
                logger.error(f"Failed to deregister {name.split('/')[-1]}. Message: {message}")
                ui.notify(f"Failed to deregister {name.split('/')[-1]}: {message}", type="negative", multi_line=True)

        with deregister_status_area:
            deregister_status_area.clear()
            summary = f"Deregistration complete. Success: {success_count}, Failed: {fail_count}."
            ui.label(summary)
            logger.info(summary)
            ui.notify(summary, type="info" if fail_count == 0 else "warning")

        await fetch_registered_agents_async( # Updated function name
            as_project, page_state.get('project_number'),
            page_state.get('selected_deregister_as_app'),
            deregister_list_container, deregister_fetch_reg_button,
            deregister_button, page_state
        )

    # Bind the refactored state update handlers
    as_project_input.on('update:model-value', handle_as_project_input_change)
    deregister_as_select.on('update:model-value', lambda: asyncio.create_task(update_deregister_app_selection()))

def update_deregister_button_state(current_page_state: dict, button: ui.button): # Renamed
    selected_names = [name for name, selected in current_page_state.get("deregister_selection", {}).items() if selected]
    button.set_enabled(bool(selected_names))

async def fetch_registered_agents_async( # Renamed
    as_project_id: str, as_project_number: Optional[str],
    agentspace_app: Optional[Dict[str, Any]], # Already optional, but good to confirm
    list_container: ui.column, fetch_button: ui.button, deregister_button: ui.button, page_state: dict,
    assistant_name: str = "default_assistant"
) -> None:
    if not all([as_project_id, as_project_number, agentspace_app]):
        ui.notify("Missing Agentspace Project ID, Number, or selected Agentspace App.", type="warning")
        return
    logger.info(f"Fetching registered agents for deregister from Agentspace App: {agentspace_app.get('engine_id') if agentspace_app else 'N/A'} in project {as_project_id}, assistant: {assistant_name}")

    fetch_button.disable()
    deregister_button.disable()
    list_container.clear()
    page_state["deregister_registered_adk_agents"] = [] # Updated key
    page_state["deregister_selection"] = {} # Updated key
    ui.notify(f"Fetching all agents from assistant '{assistant_name}'...", type="info", spinner=True)

    all_agents, error_msg = await asyncio.to_thread(
        get_all_agents_from_assistant_sync, as_project_id, as_project_number, agentspace_app, assistant_name # Uses already renamed helper
    )

    if error_msg:
        logger.error(f"Error fetching V2 registered agents: {error_msg}")
        with list_container: ui.label(error_msg).classes("text-red-500")
        ui.notify(error_msg, type="negative", multi_line=True)
        fetch_button.enable()
        return

    adk_agents = [agent for agent in all_agents if "adkAgentDefinition" in agent]
    logger.info(f"Found {len(adk_agents)} ADK agents out of {len(all_agents)} total agents.")
    page_state["deregister_registered_adk_agents"] = adk_agents # Updated key
    populate_deregister_list(adk_agents, list_container, page_state, deregister_button) # Updated function name
    fetch_button.enable()

# --- New Registration Sync Function (V2 API) ---
def register_agent_sync( # Renamed
    as_project_id: str, as_project_number: str, # Use as_project_id and as_project_number
    agentspace_app: Dict[str, Any],
    agent_engine_resource_name: str, display_name: str, description: str,
    tool_description: str, icon_uri: str, authorizations_list: Optional[List[str]]
) -> Tuple[bool, str]:
    """Synchronous function to register Agent Engine with Agentspace App using the new POST API."""
    logger.info("\n--- Registering Agent Engine with Agentspace (Sync Call) ---")
    logger.info(f"Agentspace Project: {as_project_id} (Number: {as_project_number})")
    logger.info(f"Agentspace App: {agentspace_app['engine_id']} (Location: {agentspace_app['location']})")
    logger.info(f"Agent Engine Resource: {agent_engine_resource_name}")
    logger.info(f"Display Name: {display_name}, Description: {description}, Tool Desc: {tool_description}, Icon: {icon_uri}, Auths: {authorizations_list}")
    agentspace_app_id = agentspace_app['engine_id']
    agentspace_location = agentspace_app['location']

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh token from ADC for registration.")
            raise ValueError("Failed to refresh token from ADC for registration.")
        access_token = credentials.token
        logger.info("Successfully obtained access token from ADC for registration.")

        hostname = f"{agentspace_location}-discoveryengine.googleapis.com" if agentspace_location != "global" else "discoveryengine.googleapis.com"
        api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{agentspace_location}/collections/default_collection/engines/{agentspace_app_id}/assistants/default_assistant/agents"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": as_project_id, # Use Agentspace Project ID
        }

        payload = {
            "displayName": display_name,
            "description": description,
            "icon": {"uri": icon_uri if icon_uri else "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"},
            "adk_agent_definition": {
                "tool_settings": {
                    "tool_description": tool_description
                },
                "provisioned_reasoning_engine": {
                    "reasoning_engine": agent_engine_resource_name
                }
            }
        }

        if authorizations_list:
            payload["adk_agent_definition"]["authorizations"] = authorizations_list

        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.info(f"REGISTER_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(payload, indent=2)}")

        response = requests.post(api_endpoint, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        
        response_data = response.json()
        logger.info(f"REGISTER_RESPONSE (Status {response.status_code}):\n{json.dumps(response_data, indent=2)}")
        logger.info(f"Successfully created agent resource. Name: {response_data.get('name', 'N/A')}")
        return True, f"Successfully created agent resource.\nName: {response_data.get('name', 'N/A')}\nResponse: {json.dumps(response_data, indent=2)}"

    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        msg = f"Agentspace registration API call failed: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during registration: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

# --- New Deregistration V2 Sync Functions ---
def get_all_agents_from_assistant_sync(
    as_project_id: str, as_project_number: str, # Use as_project_id and as_project_number
    agentspace_app: Dict[str, Any], assistant_name: str = "default_assistant"
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Synchronously fetches all agents (ADK and non-ADK) from a given assistant."""
    logger.info(f"Fetching all agents from assistant '{assistant_name}', AS Project: {as_project_id}, App: {agentspace_app.get('engine_id')}")
    location = agentspace_app['location']
    app_id = agentspace_app['engine_id']
    hostname = f"{location}-discoveryengine.googleapis.com" if location != "global" else "discoveryengine.googleapis.com"
    api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_name}/agents"

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token
        if not access_token:
            logger.error("Failed to refresh ADC token for agent list.")
            raise ValueError("Failed to refresh ADC token for agent list.")

        headers = {"Authorization": f"Bearer {access_token}", "X-Goog-User-Project": as_project_id} # Use Agentspace Project ID
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.info(f"GET_ALL_AGENTS_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}")

        response = requests.get(api_endpoint, headers=headers)
        response.raise_for_status()
        agents_list = response.json().get("agents", [])
        logger.info(f"GET_ALL_AGENTS_RESPONSE (Status {response.status_code}): Found {len(agents_list)} agents.")
        return agents_list, None
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        msg = f"API Error fetching agent list: {error_detail}"
        logger.error(msg)
        return [], msg
    except Exception as e:
        msg = f"Unexpected error fetching agent list: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return [], msg

def deregister_agent_sync(as_project_id: str, agent_resource_name: str) -> Tuple[bool, str]: # Renamed, as_project_id for X-Goog-User-Project
    """Synchronously deregisters a single agent using its full resource name (V2 API)."""
    logger.info(f"\n--- Deregistering Agent (Sync Call): {agent_resource_name} --- AS Project for header: {as_project_id}")

    try:
        parts = agent_resource_name.split('/')
        loc_idx = parts.index('locations') + 1
        agent_location = parts[loc_idx]
    except (ValueError, IndexError):
        return False, f"Could not parse location from agent resource name: {agent_resource_name}"
    
    logger.info(f"Parsed agent location for deregister: {agent_location}")
    
    hostname = f"{agent_location}-discoveryengine.googleapis.com" if agent_location != "global" else "discoveryengine.googleapis.com"
    api_endpoint = f"https://{hostname}/v1alpha/{agent_resource_name}"

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token
        if not access_token:
            logger.error("Failed to refresh ADC token for deregister.")
            raise ValueError("Failed to refresh ADC token for deregister.")

        headers = {"Authorization": f"Bearer {access_token}", "X-Goog-User-Project": as_project_id} # Use Agentspace Project ID
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.info(f"DEREGISTER_AGENT_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}")

        response = requests.delete(api_endpoint, headers=headers)
        response.raise_for_status()
        logger.info(f"DEREGISTER_AGENT_RESPONSE (Status {response.status_code}): {response.text if response.text else '(empty body)'}")
        logger.info(f"Successfully deregistered agent '{agent_resource_name.split('/')[-1]}'.")
        return True, f"Successfully deregistered agent '{agent_resource_name.split('/')[-1]}'."
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        msg = f"API Error during deregistration: {error_detail}"
        logger.error(msg)
        return False, msg
    except Exception as e:
        msg = f"Unexpected error during deregistration: {e}\n{traceback.format_exc()}"
        logger.error(msg)
        return False, msg

def populate_deregister_list(adk_agents: List[Dict[str,Any]], list_container: ui.column, page_state: dict, deregister_button: ui.button): # Renamed
    """Populates the UI list for V2 deregistration with filtered ADK agents."""
    logger.debug(f"Populating deregister list with {len(adk_agents)} ADK agents.")
    with list_container:
        list_container.clear()
        if not adk_agents:
            ui.label("No ADK agents found registered in this assistant.")
            ui.notify("No ADK agents found for deregistration.", type="info")
        else:
            ui.label(f"Found {len(adk_agents)} ADK agents:").classes("font-semibold")
            for agent_data in adk_agents:
                agent_name = agent_data.get("name", "Unknown Name")
                display_name = agent_data.get("displayName", "N/A")
                reasoning_engine_info = agent_data.get("adkAgentDefinition", {}).get("provisionedReasoningEngine", {}).get("reasoningEngine", "N/A")

                with ui.card().classes("w-full p-2 my-1"):
                    with ui.row().classes("items-center"):
                        checkbox = ui.checkbox().bind_value(page_state["deregister_selection"], agent_name).classes("mr-2") # Updated key
                        checkbox.on('update:model-value', lambda: update_deregister_button_state(page_state, deregister_button)) # Uses renamed func
                        with ui.column().classes("gap-0"):
                            ui.label(f"{display_name}").classes("font-medium")
                            ui.label(f"Name: ...{agent_name[-30:]}").classes("text-xs text-gray-500")
                            ui.label(f"Engine: {reasoning_engine_info.split('/')[-1]}").classes("text-xs text-gray-500")
            update_deregister_button_state(page_state, deregister_button) # Uses renamed func
            ui.notify(f"Successfully fetched and filtered {len(adk_agents)} ADK agents.", type="positive")

# --- Main Execution ---
if __name__ in {"__main__", "__mp_main__"}:
    load_dotenv(override=True)
    # script_dir_manager is already defined for logger
    if script_dir_manager not in sys.path: sys.path.insert(0, script_dir_manager)
    parent_dir = os.path.dirname(script_dir_manager)
    if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
    utils_path = os.path.join(script_dir_manager, "deployment_utils")
    if os.path.isdir(utils_path) and utils_path not in sys.path: sys.path.insert(0, utils_path)

    logger.info("Starting ADK Lifecycle Manager WebUI.")

    ui.run(title="Agent Lifecycle Manager", favicon="🛠️", dark=None, port=8080)
