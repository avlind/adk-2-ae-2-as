

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
import logging
import time
import traceback
from typing import Any, Dict

from nicegui import ui
from vertexai import agent_engines
from vertexai.preview.reasoning_engines import AdkApp

from agent_manager.constants import WEBUI_AGENTDEPLOYMENT_HELPTEXT
from agent_manager.helpers import (
    _BASE_REQUIREMENTS,
    get_agent_root_nicegui,
    init_vertex_ai,
    update_timer,
)

logger = logging.getLogger("WebUIManagerActivity")


def create_deploy_tab(
    page_state: Dict[str, Any],
    ae_project_input: ui.input,
    location_select: ui.select,
    bucket_input: ui.input,
    agent_configs: Dict[str, Any],
) -> None:
    with ui.tab_panel("deploy"):
        with ui.column().classes("w-full p-4 gap-4"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Select Agent Configuration to Deploy").classes(
                    "text-xl font-semibold"
                )
                info_icon = ui.icon("info", color="primary").classes(
                    "cursor-pointer text-lg"
                )
                with ui.dialog() as info_dialog, ui.card():
                    ui.label(WEBUI_AGENTDEPLOYMENT_HELPTEXT)
                    ui.button("Close", on_click=info_dialog.close).classes("mt-4")
                info_icon.on("click", info_dialog.open)

            deploy_agent_selection_area = ui.grid(columns=2).classes("w-full gap-2")
            deploy_button = ui.button(
                "Deploy Agent",
                icon="cloud_upload",
                on_click=lambda: start_deployment(),
            )
            deploy_button.disable()
            deploy_status_area = ui.column().classes(
                "w-full mt-2 p-4 border rounded-lg bg-gray-50 dark:bg-gray-900"
            )
            with deploy_status_area:
                ui.label("Configure deployment and select an agent.").classes(
                    "text-gray-500"
                )

    def handle_deploy_agent_selection(agent_key: str):
        if not all(
            [ae_project_input.value, location_select.value, bucket_input.value]
        ):
            ui.notify(
                "Please configure Agent Engine Project, Location, and Bucket in the side panel first.",
                type="warning",
            )
            if page_state["deploy_radio_group"]:
                page_state["deploy_radio_group"].set_value(None)
            return

        if page_state["previous_selected_card"]:
            page_state["previous_selected_card"].classes(
                remove="border-blue-500 dark:border-blue-400"
            )

        page_state["selected_agent_key"] = agent_key
        page_state["selected_agent_config"] = agent_configs.get(agent_key)

        current_card = page_state["agent_cards"].get(agent_key)
        if current_card:
            current_card.classes(add="border-blue-500 dark:border-blue-400")
            page_state["previous_selected_card"] = current_card

        logger.debug(f"Selected agent for deploy: {agent_key}")
        update_deploy_button_state()

    def update_deploy_button_state():
        core_config_ok = (
            ae_project_input.value
            and location_select.value
            and bucket_input.value
        )
        agent_config_selected = page_state["selected_agent_key"] is not None
        if core_config_ok and agent_config_selected:
            deploy_button.enable()
        else:
            deploy_button.disable()

    with deploy_agent_selection_area:
        if not agent_configs or "error" in agent_configs:
            ui.label("No agent configurations found or error loading them.").classes(
                "text-red-500"
            )
        else:
            page_state["deploy_radio_group"] = ui.radio(
                [key for key in agent_configs.keys()],
                on_change=lambda e: handle_deploy_agent_selection(e.value),
            ).props("hidden")

            for key, config in agent_configs.items():
                card = ui.card().classes(
                    "w-full p-3 cursor-pointer hover:shadow-md border-2 border-transparent"
                )
                page_state["agent_cards"][key] = card
                with card.on(
                    "click",
                    lambda k=key: page_state["deploy_radio_group"].set_value(k),
                ):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label(
                            f"{config.get('ae_display_name', key)}"
                        ).classes("text-lg font-medium")
                    with ui.column().classes(
                        "gap-0 mt-1 text-sm text-gray-600 dark:text-gray-400"
                    ):
                        ui.label(f"Config Key: {key}")
                        ui.label(
                            f"Engine Name: {config.get('ae_display_name', 'N/A')}"
                        )
                        ui.label(f"Description: {config.get('description', 'N/A')}")
                        ui.label(
                            f"Module: {config.get('module_path', 'N/A')}:{config.get('root_variable', 'N/A')}"
                        )

    async def start_deployment():
        ae_project = ae_project_input.value
        location = location_select.value
        bucket = bucket_input.value
        agent_key = page_state["selected_agent_key"]
        agent_config = page_state["selected_agent_config"]

        if not all([ae_project, location, bucket, agent_key]):
            ui.notify(
                "Please provide Agent Engine Project ID, Location, Bucket, and select an Agent.",
                type="warning",
            )
            return
        if not agent_config:
            ui.notify(
                "Internal Error: No agent configuration selected.", type="negative"
            )
            return

        with ui.dialog() as confirm_dialog, ui.card():
            ui.label("Confirm Agent Deployment").classes("text-xl font-bold")
            with ui.column().classes("gap-1 mt-2"):
                ui.label("Agent Engine Project:").classes("font-semibold")
                ui.label(f"{ae_project}")
                ui.label("Location:").classes("font-semibold")
                ui.label(f"{location}")
                ui.label("Bucket:").classes("font-semibold")
                ui.label(f"gs://{bucket}")
                ui.label("Agent Config Key:").classes("font-semibold")
                ui.label(f"{agent_key}")

            default_display_name = agent_config.get(
                "ae_display_name", f"{agent_key.replace('_', ' ').title()} Agent"
            )
            logger.info(
                f"Confirming deployment for agent: {agent_key}, AE Project: {ae_project}, Location: {location}, Bucket: {bucket}, Display Name: {default_display_name}"
            )
            default_description = agent_config.get("description", f"Agent: {agent_key}")
            display_name_input = ui.input(
                "Agent Engine Name", value=default_display_name
            ).props("outlined dense").classes("w-full mt-3")
            description_input = ui.textarea(
                "Description", value=default_description
            ).props("outlined dense").classes("w-full mt-2")

            ui.label("Proceed with deployment?").classes("mt-4")
            with ui.row().classes("mt-4 w-full justify-end"):
                ui.button("Cancel", on_click=confirm_dialog.close, color="gray")
                ui.button(
                    "Deploy",
                    on_click=lambda: (
                        confirm_dialog.close(),
                        asyncio.create_task(
                            run_deployment_async(
                                ae_project,
                                location,
                                bucket,
                                agent_key,
                                agent_config,
                                display_name_input.value,
                                description_input.value,
                                deploy_button,
                                deploy_status_area,
                            )
                        ),
                    ),
                )
        await confirm_dialog


async def run_deployment_async(
    ae_project_id: str,
    location: str,
    bucket: str,
    agent_name: str,
    agent_config: dict,
    display_name: str,
    description: str,
    deploy_button: ui.button,
    status_area: ui.column,
) -> None:
    deploy_button.disable()
    logger.info(
        f"Starting deployment for agent: {agent_name} in {ae_project_id}/{location}, bucket: {bucket}."
    )
    logger.info(f"Display Name: {display_name}, Description: {description}")

    status_area.clear()

    timer_label = None
    stop_timer_event = asyncio.Event()

    with status_area:
        ui.label(f"Starting deployment for: {agent_name}").classes(
            "text-lg font-semibold"
        )
        progress_label = ui.label("Initializing Vertex AI SDK...")
        spinner = ui.spinner(size="lg", color="primary")
        timer_label = ui.label("Elapsed Time: 00:00").classes(
            "text-sm text-gray-500 mt-1"
        )

    init_success, init_error_msg = await asyncio.to_thread(
        init_vertex_ai, ae_project_id, location, bucket
    )

    if not init_success:
        spinner.set_visibility(False)
        logger.error(
            f"Vertex AI Initialization Failed for deployment: {init_error_msg}"
        )
        with status_area:
            progress_label.set_text(f"Error: {init_error_msg}")
        ui.notify(
            f"Vertex AI Initialization Failed: {init_error_msg}",
            type="negative",
            multi_line=True,
            close_button=True,
        )
        deploy_button.enable()
        return

    with status_area:
        progress_label.set_text("Vertex AI Initialized. Importing agent code...")
        ui.notify("Vertex AI Initialized Successfully.", type="positive")

    root_agent, agent_env_vars, import_error_msg = await get_agent_root_nicegui(
        agent_config
    )
    if root_agent is None:
        spinner.set_visibility(False)
        logger.error(f"Agent Import Failed for deployment: {import_error_msg}")
        with status_area:
            progress_label.set_text(f"Error: {import_error_msg}")
        ui.notify(
            f"Agent Import Failed: {import_error_msg}",
            type="negative",
            multi_line=True,
            close_button=True,
        )
        deploy_button.enable()
        return

    with status_area:
        progress_label.set_text("Agent code imported. Preparing deployment...")

    adk_app = AdkApp(agent=root_agent, enable_tracing=True)
    agent_specific_reqs = agent_config.get("requirements", [])
    if not isinstance(agent_specific_reqs, list):
        agent_specific_reqs = []
    combined_requirements = sorted(
        list(set(_BASE_REQUIREMENTS) | set(agent_specific_reqs))
    )
    extra_packages = agent_config.get("extra_packages", [])
    if not isinstance(extra_packages, list):
        extra_packages = []

    with status_area:
        progress_label.set_text(
            "Configuration ready. Deploying ADK to Agent Engine (this may take 2-5 minutes)..."
        )

    log_message_details = f"\n--- Deployment Details for {agent_name} ---\n"
    log_message_details += f"Display Name: {display_name}\n"
    log_message_details += f"Description: {description}\n"
    log_message_details += f"Requirements: {combined_requirements}\n"
    log_message_details += f"Extra Packages: {extra_packages}\n"
    if agent_env_vars:
        log_message_details += "Environment Variables from Agent's .env file:\n"
        for key, val in agent_env_vars.items():
            log_message_details += (
                f"- {key}={'[value_set]' if val else '[empty_value]'}\n"
            )
        with status_area:
            ui.label(
                "Loaded Environment Variables from Agent's .env:"
            ).classes("font-semibold mt-2")
            for key, val in agent_env_vars.items():
                ui.label(
                    f"- {key}: {val[:30]}{'...' if len(val)>30 else ''}"
                ).classes("text-xs")
    logger.info(log_message_details + "--------------------------")

    start_time = time.monotonic()
    _ = asyncio.create_task(
        update_timer(start_time, timer_label, stop_timer_event, status_area)
    )
    remote_agent = None
    deployment_error = None
    try:

        def sync_create_agent():
            return agent_engines.create(
                adk_app,
                requirements=combined_requirements,
                extra_packages=extra_packages,
                display_name=display_name,
                description=description,
                env_vars=agent_env_vars,
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
            success_msg = (
                f"Successfully created remote agent: {remote_agent.resource_name}"
            )
            logger.info(
                f"--- Agent creation complete for {agent_name} ({duration_str}) --- Resource: {remote_agent.resource_name}"
            )
            with status_area:
                progress_label.set_text(
                    f"Deployment Successful! (Duration: {duration_str})"
                )
                ui.label("Resource Name:").classes("font-semibold mt-2")
                ui.markdown(f"`{remote_agent.resource_name}`").classes("text-sm")
                ui.notify(
                    success_msg,
                    type="positive",
                    multi_line=True,
                    close_button=True,
                )
        else:
            error_msg = f"Error during agent engine creation: {deployment_error}"
            logger.error(
                f"Deployment Failed for {agent_name}! (Duration: {duration_str}). Error: {deployment_error}\nTraceback: {traceback.format_exc()}"
            )
            with status_area:
                progress_label.set_text(
                    f"Deployment Failed! (Duration: {duration_str})"
                )
                ui.label("Error Details:").classes(
                    "font-semibold mt-2 text-red-600"
                )
                ui.html(
                    f"<pre class='text-xs p-2 bg-gray-100 dark:bg-gray-800 rounded overflow-auto'>{traceback.format_exc()}</pre>"
                )
                ui.notify(
                    error_msg,
                    type="negative",
                    multi_line=True,
                    close_button=True,
                )

        deploy_button.enable()
