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

# --- Standard Library Imports ---
import asyncio
import copy
import json
import logging
import os
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler

# --- Third-party Imports ---
import requests
from dotenv import load_dotenv
from nicegui import ui

# --- Google Cloud & Auth Imports ---
try:
    import google.auth
    import google.auth.transport.requests
    import googleapiclient.discovery  # Added for Project Number lookup
    import googleapiclient.errors  # Added for Project Number lookup
except ImportError:
    print("Error: Could not import Google API libraries.")
    print("Please install them: pip install requests google-auth google-api-python-client python-dotenv nicegui")
    sys.exit(1)

# --- Constants ---
API_BASE_URL = "https://discoveryengine.googleapis.com/v1alpha"
DEFAULT_LOCATION = "global"  # Authorizations are typically global
# --- Logger Setup ---
LOG_FILE_NAME = "webui_activity.log"
script_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(script_dir, LOG_FILE_NAME)

logger = logging.getLogger("WebUIActivity")
logger.setLevel(logging.INFO)

# Use TimedRotatingFileHandler for daily log rotation
file_handler = TimedRotatingFileHandler(
    log_file_path,
    when="midnight",  # Rotate at midnight
    interval=1,       # Daily rotation
    backupCount=0,    # Keep all old log files (no automatic deletion)
    encoding='utf-8'  # Good practice to specify encoding
)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.propagate = False  # Prevent duplicate logs if root logger is configured

# --- Helper Functions ---

def get_access_token_and_credentials_sync() -> tuple[str | None, google.auth.credentials.Credentials | None, str | None]:
    """Gets ADC access token and credentials synchronously."""
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

async def get_access_token_and_credentials_async() -> tuple[str | None, google.auth.credentials.Credentials | None, str | None]:
    """Gets ADC access token and credentials asynchronously."""
    return await asyncio.to_thread(get_access_token_and_credentials_sync)

def get_project_number_sync(project_id: str, credentials: google.auth.credentials.Credentials) -> tuple[str | None, str | None]:
    """Gets the project number for a given project ID using provided credentials."""
    try:
        logger.info(f"Attempting to fetch project number for project ID: {project_id}")
        service = googleapiclient.discovery.build('cloudresourcemanager', 'v1', credentials=credentials)
        request = service.projects().get(projectId=project_id)
        response = request.execute()
        project_number = response.get('projectNumber')

        if not project_number:
            err_msg = f"Could not find project number for project ID '{project_id}' in API response. Response: {response}"
            logger.error(err_msg)
            return None, err_msg
        logger.info(f"Successfully fetched project number for {project_id}: {project_number}")
        return str(project_number), None
    except googleapiclient.errors.HttpError as e:
        error_content = e.content.decode('utf-8') if e.content else "No error content"
        try:
            error_json = json.loads(error_content)
            error_message_detail = error_json.get("error", {}).get("message", error_content)
        except json.JSONDecodeError:
            error_message_detail = error_content
        full_error = f"API error getting project number for '{project_id}': {e.resp.status} {e.resp.reason} - {error_message_detail}"
        logger.error(full_error)
        return None, full_error
    except Exception as e:
        full_error = f"Unexpected error getting project number for '{project_id}': {e}\n{traceback.format_exc()}"
        logger.error(full_error)
        return None, full_error

async def get_project_number_async(project_id: str, credentials: google.auth.credentials.Credentials) -> tuple[str | None, str | None]:
    """Gets the project number for a given project ID asynchronously."""
    return await asyncio.to_thread(get_project_number_sync, project_id, credentials)

def create_authorization_sync(
    target_project_id: str, # For X-Goog-User-Project header
    target_project_number: str, # For URL path and payload name
    auth_id: str,
    client_id: str,
    client_secret: str,
    auth_uri: str,
    token_uri: str,
    access_token: str
) -> tuple[bool, str]:
    """Synchronous function to create an Agentspace Authorization."""
    url = f"{API_BASE_URL}/projects/{target_project_number}/locations/{DEFAULT_LOCATION}/authorizations?authorizationId={auth_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": target_project_id,
    }
    payload = {
        "name": f"projects/{target_project_number}/locations/{DEFAULT_LOCATION}/authorizations/{auth_id}",
        "serverSideOauth2": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "authorizationUri": auth_uri,
            "tokenUri": token_uri,
        }
    }
    try:
        logger.info(f"Attempting to create authorization: {auth_id} in project {target_project_id} (number: {target_project_number})")

        # Log the request details for curl replication
        # Redact client_secret for logging
        logged_payload = copy.deepcopy(payload)
        if "serverSideOauth2" in logged_payload and "clientSecret" in logged_payload["serverSideOauth2"]:
            logged_payload["serverSideOauth2"]["clientSecret"] = "[redacted]"

        # Mask token in logs for security
        log_headers = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}

        request_log_message = (
            f"CREATE_AUTHORIZATION_REQUEST:\n"
            f"  Method: POST\n"
            f"  URL: {url}\n"
            f"  Headers: {json.dumps(log_headers, indent=2)}\n"
            f"  Payload: {json.dumps(logged_payload, indent=2)}"
        )
        logger.info(request_log_message)

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"CREATE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}")
        return True, f"Successfully created authorization '{auth_id}'.\nResponse: {json.dumps(response_json, indent=2)}"
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code}, Body: {e.response.text}" if e.response else str(e)
        msg = f"API call to create authorization failed: {error_detail}"
        print(msg)
        return False, msg
    except Exception as e:
        msg = f"An unexpected error occurred during authorization creation: {e}\n{traceback.format_exc()}"
        print(msg)
        return False, msg

def delete_authorization_sync(
    target_project_id: str, # For X-Goog-User-Project header
    target_project_number: str, # For URL path
    auth_id: str,
    access_token: str
) -> tuple[bool, str]:
    """
    Synchronous function to delete an Agentspace Authorization.
    Uses project number in the URL path and project ID for X-Goog-User-Project header.
    """
    url = f"{API_BASE_URL}/projects/{target_project_number}/locations/{DEFAULT_LOCATION}/authorizations/{auth_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json", # Included as per doc's curl, though often optional for DELETE
        "X-Goog-User-Project": target_project_id,
    }
    try:
        logger.info(f"Attempting to delete authorization: {auth_id} in project {target_project_id} (number: {target_project_number})")

        # Mask token in logs for security
        log_headers = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}

        request_log_message = (
            f"DELETE_AUTHORIZATION_REQUEST:\n"
            f"  Method: DELETE\n"
            f"  URL: {url}\n"
            f"  Headers: {json.dumps(log_headers, indent=2)}"
        )
        logger.info(request_log_message)

        response = requests.delete(url, headers=headers)
        response.raise_for_status()

        # Log response (even if empty, log status)
        response_text = response.text
        try:
            response_json = response.json() # Try to parse as JSON
            logger.info(f"DELETE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            logger.info(f"DELETE_AUTHORIZATION_RESPONSE (Status {response.status_code}):\n{response_text if response_text else '(empty body)'}")

        # Successful DELETE might return 200 OK (often with an empty or specific "done" body) or 204 No Content.
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

# --- NiceGUI Page Setup ---
@ui.page("/")
async def main_page():
    """Main NiceGUI page for managing Agentspace Authorizations."""
    ui.query('body').classes(add='text-base') # Ensure base font size for consistency
    with ui.header(elevated=True).classes("items-center justify-between"):
        ui.label("Agentspace Authorization Manager").classes("text-2xl font-bold")

    # --- Configuration Section ---
    with ui.card().classes("w-full p-4 mb-4 shadow-md"):
        ui.label("GCP Configuration").classes("text-xl font-semibold mb-2")
        project_input = ui.input(
            "GCP Project ID",
            value=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            placeholder="your-gcp-project-id"
        ).props("outlined dense").classes('w-full text-base')
        ui.label(f"Authorization Location: {DEFAULT_LOCATION} (fixed for this API)").classes("text-sm text-gray-500 mt-1")

    # --- Main Content with Tabs ---
    with ui.tabs().classes('w-full') as tabs:
        create_tab_button = ui.tab('Create Authorization', icon='add_circle_outline')
        delete_tab_button = ui.tab('Delete Authorization', icon='delete_outline')

    with ui.tab_panels(tabs, value=create_tab_button).classes('w-full mt-4'):
        # --- Create Authorization Tab Panel ---
        with ui.tab_panel(create_tab_button):
            with ui.column().classes("w-full p-4 gap-3"): # Reduced gap slightly
                ui.label("Create New Agentspace Authorization").classes("text-xl font-semibold mb-2")
                auth_id_create_input = ui.input("Authorization ID", placeholder="e.g., my-google-oauth-client").props("outlined dense clearable").classes("w-full")
                client_id_input = ui.input("OAuth Client ID").props("outlined dense clearable").classes("w-full")
                client_secret_input = ui.input("OAuth Client Secret", password=True, password_toggle_button=True).props("outlined dense clearable").classes("w-full")
                auth_uri_input = ui.input("OAuth Authorization URI", placeholder="https://accounts.google.com/o/oauth2/v2/auth").props("outlined dense clearable").classes("w-full")
                token_uri_input = ui.input("OAuth Token URI", placeholder="https://oauth2.googleapis.com/token").props("outlined dense clearable").classes("w-full")

                create_button = ui.button("Create Authorization", icon="save", on_click=lambda: start_create_authorization())
                create_status_area = ui.column().classes("w-full mt-3 p-3 border rounded bg-gray-50 dark:bg-gray-800 min-h-[60px]")
                with create_status_area:
                    ui.label("Fill in all details above and click 'Create Authorization'.").classes("text-sm text-gray-500 dark:text-gray-400")

        # --- Delete Authorization Tab Panel ---
        with ui.tab_panel(delete_tab_button):
            with ui.column().classes("w-full p-4 gap-3"):
                ui.label("Delete Agentspace Authorization").classes("text-xl font-semibold mb-2")
                auth_id_delete_input = ui.input("Authorization ID to Delete", placeholder="e.g., my-google-oauth-client").props("outlined dense clearable").classes("w-full")

                delete_button = ui.button("Delete Authorization", icon="delete_forever", color="red", on_click=lambda: start_delete_authorization())
                delete_status_area = ui.column().classes("w-full mt-3 p-3 border rounded bg-gray-50 dark:bg-gray-800 min-h-[60px]")
                with delete_status_area:
                    ui.label("Enter the Authorization ID to remove and click 'Delete Authorization'.").classes("text-sm text-gray-500 dark:text-gray-400")

    # --- Logic for Create Authorization ---
    async def start_create_authorization():
        project_id = project_input.value
        auth_id = auth_id_create_input.value
        client_id = client_id_input.value
        client_secret = client_secret_input.value
        auth_uri = auth_uri_input.value
        token_uri = token_uri_input.value

        if not all([project_id, auth_id, client_id, client_secret, auth_uri, token_uri]):
            ui.notify("All fields are required for creation. Please check your inputs.", type="warning")
            return

        create_button.disable()
        with create_status_area:
            create_status_area.clear()
            with ui.row().classes("items-center"):
                ui.spinner(size="lg").classes("mr-2")
                ui.label("Attempting to create authorization...")

        access_token, credentials, token_error = await get_access_token_and_credentials_async()
        if token_error:
            with create_status_area:
                create_status_area.clear()
                ui.label(f"Error getting access token: {token_error}").classes("text-red-600")
            ui.notify(f"Access Token/Credentials Error: {token_error}", type="negative", multi_line=True, close_button=True)
            create_button.enable()
            return
        if not credentials: # Should not happen if token_error is None, but good practice
            with create_status_area:
                create_status_area.clear()
                ui.label("Failed to obtain credentials.").classes("text-red-600")
            ui.notify("Failed to obtain credentials.", type="negative", multi_line=True, close_button=True)
            create_button.enable()
            return

        project_number, project_number_error = await get_project_number_async(project_id, credentials)
        if project_number_error:
            with create_status_area:
                create_status_area.clear()
                ui.label(f"Error getting project number: {project_number_error}").classes("text-red-600")
            ui.notify(f"Project Number Error: {project_number_error}", type="negative", multi_line=True, close_button=True)
            create_button.enable()
            return

        success, message = await asyncio.to_thread(
            create_authorization_sync, # Pass project_id (for header) and project_number (for URL)
            project_id, project_number, auth_id, client_id, client_secret, auth_uri, token_uri, access_token
        )

        with create_status_area:
            create_status_area.clear()
            if success:
                ui.html(f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                ui.notify("Authorization created successfully!", type="positive", multi_line=True, close_button=True)
                # Clear inputs on success for convenience
                auth_id_create_input.set_value("")
                client_id_input.set_value("")
                client_secret_input.set_value("")
                auth_uri_input.set_value("")
                token_uri_input.set_value("")
            else:
                ui.html(f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                ui.notify("Failed to create authorization.", type="negative", multi_line=True, close_button=True)
        create_button.enable()

    # --- Logic for Delete Authorization ---
    async def start_delete_authorization():
        project_id = project_input.value
        auth_id = auth_id_delete_input.value

        if not all([project_id, auth_id]):
            ui.notify("Project ID and Authorization ID are required for deletion.", type="warning")
            return

        # Confirmation Dialog before actual deletion
        with ui.dialog() as confirm_dialog, ui.card():
            ui.label(f"Are you sure you want to delete authorization '{auth_id}' from project '{project_id}'?").classes("text-lg mb-2")
            ui.label("This action cannot be undone.").classes("font-semibold text-red-600")
            with ui.row().classes("mt-5 w-full justify-end gap-2"):
                ui.button("Cancel", on_click=confirm_dialog.close, color="gray")
                ui.button("Delete Permanently",
                          on_click=lambda: (confirm_dialog.close(), asyncio.create_task(run_actual_deletion(project_id, auth_id))),
                          color="red")
        await confirm_dialog

    async def run_actual_deletion(project_id: str, auth_id: str):
        delete_button.disable()
        with delete_status_area:
            delete_status_area.clear()
            with ui.row().classes("items-center"):
                ui.spinner(size="lg").classes("mr-2")
                ui.label(f"Attempting to delete authorization '{auth_id}'...")

        access_token, credentials, token_error = await get_access_token_and_credentials_async()
        if token_error:
            with delete_status_area:
                delete_status_area.clear()
                ui.label(f"Error getting access token: {token_error}").classes("text-red-600")
            ui.notify(f"Access Token/Credentials Error: {token_error}", type="negative", multi_line=True, close_button=True)
            delete_button.enable()
            return
        if not credentials:
            with delete_status_area:
                delete_status_area.clear()
                ui.label("Failed to obtain credentials.").classes("text-red-600")
            ui.notify("Failed to obtain credentials.", type="negative", multi_line=True, close_button=True)
            delete_button.enable()
            return

        project_number, project_number_error = await get_project_number_async(project_id, credentials)
        if project_number_error:
            with delete_status_area:
                delete_status_area.clear()
                ui.label(f"Error getting project number: {project_number_error}").classes("text-red-600")
            ui.notify(f"Project Number Error: {project_number_error}", type="negative", multi_line=True, close_button=True)
            delete_button.enable()
            return

        success, message = await asyncio.to_thread(delete_authorization_sync, project_id, project_number, auth_id, access_token)
        with delete_status_area:
            delete_status_area.clear()
            if success:
                ui.html(f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                ui.notify("Authorization deleted successfully!", type="positive", multi_line=True, close_button=True)
                auth_id_delete_input.set_value("") # Clear input on success
            else:
                ui.html(f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>")
                ui.notify("Failed to delete authorization.", type="negative", multi_line=True, close_button=True)
        delete_button.enable()

# --- Main Execution ---
if __name__ in {"__main__", "__mp_main__"}:
    load_dotenv(override=True) # Load .env file if present (e.g., for GOOGLE_CLOUD_PROJECT)


    ui.run(
        title="Agentspace Authorization Manager",
        favicon="🔑", # Key emoji for favicon
        dark=None,    # Respect system/browser preference for dark/light mode
        port=8081     # Use a different port to avoid conflicts
    )
