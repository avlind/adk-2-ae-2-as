
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

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from dotenv import load_dotenv
from nicegui import Client, ui

from agent_manager.auth_tab import create_auth_tab
from agent_manager.deploy_tab import create_deploy_tab
from agent_manager.deregister_tab import create_deregister_tab
from agent_manager.destroy_tab import create_destroy_tab
from agent_manager.helpers import get_current_principal
from agent_manager.register_tab import create_register_tab
from agent_manager.test_tab import create_test_tab
from agent_manager.update_tab import create_update_tab

__version__ = "0.6"

# --- Configuration Loading ---
try:
    from agent_manager.constants import (
        SUPPORTED_REGIONS,
    )
    from deployment_utils.deployment_configs import (
        AGENT_CONFIGS,
    )
except ImportError as e:
    print(
        "Error: Could not import from 'deployment_utils'. "
        f"Ensure 'deployment_configs.py' and 'constants.py' exist. Details: {e}"
    )
    AGENT_CONFIGS = {"error": {"ae_display_name": "Import Error"}}
    SUPPORTED_REGIONS = ["us-central1"]
    IMPORT_ERROR_MESSAGE = (
        "Failed to import 'AGENT_CONFIGS' or 'SUPPORTED_REGIONS' from 'deployment_utils'. "
        "Please ensure 'deployment_configs.py' and 'constants.py' exist in the 'deployment_utils' directory "
        "relative to this script, and that the directory contains an `__init__.py` file. Run: pip install -r requirements.txt"
    )
else:
    IMPORT_ERROR_MESSAGE = None

# --- Logger Setup ---
MANAGER_LOG_FILE_NAME = "webui_manager_activity.log"
script_dir_manager = os.path.dirname(os.path.abspath(__file__))
manager_log_file_path = os.path.join(script_dir_manager, MANAGER_LOG_FILE_NAME)

logger = logging.getLogger("WebUIManagerActivity")
logger.setLevel(logging.INFO)

manager_file_handler = TimedRotatingFileHandler(
    manager_log_file_path,
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8",
)
manager_file_handler.setLevel(logging.INFO)
manager_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s"
)
manager_file_handler.setFormatter(manager_formatter)
logger.addHandler(manager_file_handler)
logger.propagate = False


@ui.page("/")
async def main_page(client: Client):
    page_state = {
        "selected_agent_key": None,
        "selected_agent_config": None,
        "deploy_radio_group": None,
        "agent_cards": {},
        "previous_selected_card": None,
        "destroy_agents": [],
        "destroy_selected": {},
        "register_agent_engines": [],
        "register_agentspaces": [],
        "project_number": None,
        "deregister_agentspaces": [],
        "deregister_registered_adk_agents": [],
        "deregister_selection": {},
        "selected_deregister_as_app": None,
        "register_authorizations_list": [],
        "project_id_input_timer": None,
        "test_username": "test-user",
        "test_available_agents": [],
        "test_selected_agent_resource_name": None,
        "test_remote_agent_instance": None,
        "test_chat_session_id": None,
        "test_is_chatting": False,
    }

    ui.query("body").classes(add="text-base")
    header = ui.header(elevated=True).classes("items-center justify-between")
    with header:
        ui.label(f"ADK on Agent Engine: Lifecycle Manager v{__version__}").classes(
            "text-2xl font-bold"
        )

    if IMPORT_ERROR_MESSAGE:
        with ui.card().classes("w-full bg-red-100 dark:bg-red-900"):
            ui.label("Configuration Error").classes(
                "text-xl font-bold text-red-700 dark:text-red-300"
            )
            ui.label(IMPORT_ERROR_MESSAGE).classes(
                "text-red-600 dark:text-red-400"
            )
            logger.critical(f"Import error encountered: {IMPORT_ERROR_MESSAGE}")
        return

    with ui.right_drawer(
        top_corner=True, bottom_corner=True
    ).classes("bg-gray-100 dark:bg-gray-800 p-4 flex flex-col").props(
        "bordered"
    ) as right_drawer:
        ui.label("Configuration").classes("text-xl font-semibold mb-4")
        with ui.column().classes("gap-4 w-full grow"):
            with ui.card().classes("w-full p-4"):
                ui.label("GCP Project Settings").classes(
                    "text-lg font-semibold mb-2"
                )
                common_project_default = os.getenv("GOOGLE_CLOUD_PROJECT", "")
                ae_project_input = (
                    ui.input(
                        "Agent Engine GCP Project ID",
                        value=os.getenv(
                            "AGENTENGINE_GCP_PROJECT", common_project_default
                        ),
                    )
                    .props("outlined dense")
                    .classes("w-full text-base")
                    .tooltip(
                        "Project ID for deploying and managing Agent Engines."
                    )
                )

                as_project_input = (
                    ui.input(
                        "Agentspace GCP Project ID",
                        value=os.getenv(
                            "AGENTSPACE_GCP_PROJECT", common_project_default
                        ),
                    )
                    .props("outlined dense")
                    .classes("w-full text-base")
                    .tooltip(
                        "Project ID for the Agentspace (Discovery Engine App) to register/deregister agents."
                    )
                )

                ui.label("Location Settings").classes(
                    "text-lg font-semibold mt-3 mb-2"
                )
                location_select = ui.select(
                    SUPPORTED_REGIONS,
                    label="Agent Engine GCP Location",
                    value=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
                ).props("outlined dense").classes("w-full text-base")
                agentspace_locations_options = ["global", "us", "eu"]
                default_agentspace_locations = os.getenv(
                    "AGENTSPACE_LOCATIONS", "global,us"
                ).split(",")
                agentspace_locations_select = ui.select(
                    agentspace_locations_options,
                    label="Agentspace Locations (for App Lookup)",
                    multiple=True,
                    value=default_agentspace_locations,
                ).props("outlined dense").classes("w-full text-base")
                bucket_input = (
                    ui.input(
                        "GCS Staging Bucket (Deploy)",
                        value=os.getenv("AGENTENGINE_STAGING_BUCKET", ""),
                    )
                    .props("outlined dense prefix=gs://")
                    .classes("w-full text-base")
                )

            ui.element("div").classes("grow")
            ui.html("Created by Aaron Lind<br>GitHub: avlind").classes(
                "text-xs text-gray-500 dark:text-gray-400"
            )
            principal = await get_current_principal()
            ui.html(f"<br>ADC Principal: {principal}").classes(
                "text-xs text-gray-500 dark:text-gray-400"
            )

    with header:
        ui.button(on_click=lambda: right_drawer.toggle(), icon="menu").props(
            "flat color=white"
        ).classes("ml-auto")

    with ui.tabs().classes("w-full") as tabs:
        ui.tab("deploy", label="Deploy", icon="rocket_launch")
        ui.tab("update", label="Update", icon="update")
        ui.tab("test", label="Test", icon="chat")
        ui.tab("destroy", label="Destroy", icon="delete_forever")
        ui.tab("agentspace_auth", label="Manage AuthN", icon="admin_panel_settings")
        ui.tab("register", label="Register", icon="assignment")
        ui.tab("deregister", label="Deregister", icon="assignment_return")

    with ui.tab_panels(tabs, value="deploy").classes("w-full"):
        create_deploy_tab(
            page_state,
            ae_project_input,
            location_select,
            bucket_input,
            AGENT_CONFIGS,
        )
        create_update_tab(page_state, ae_project_input, location_select, bucket_input, AGENT_CONFIGS)
        create_test_tab(page_state, ae_project_input, location_select)
        create_destroy_tab(page_state, ae_project_input, location_select)
        create_auth_tab(page_state, as_project_input)
        create_register_tab(
            page_state,
            ae_project_input,
            location_select,
            as_project_input,
            agentspace_locations_select,
            AGENT_CONFIGS,
        )
        create_deregister_tab(
            page_state, as_project_input, agentspace_locations_select
        )


if __name__ in {"__main__", "__mp_main__"}:
    load_dotenv(override=True)
    script_dir_manager = os.path.dirname(os.path.abspath(__file__))
    if script_dir_manager not in sys.path:
        sys.path.insert(0, script_dir_manager)
    parent_dir = os.path.dirname(script_dir_manager)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    

    logger.info("Starting ADK Lifecycle Manager WebUI.")

    ui.run(title="Agent Lifecycle Manager", favicon="🛠️", dark=None, port=8080)
