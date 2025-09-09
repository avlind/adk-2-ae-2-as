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

from agent_manager.helpers import (
    _BASE_REQUIREMENTS,
    _fetch_vertex_ai_resources,
    get_agent_root_nicegui,
    init_vertex_ai,
    update_timer,
)

logger = logging.getLogger("WebUIManagerActivity")


def create_update_tab(
    page_state: Dict[str, Any],
    ae_project_input: ui.input,
    location_select: ui.select,
    bucket_input: ui.input,
    agent_configs: Dict[str, Any],
) -> None:
    with ui.tab_panel("update"):
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("Update an existing Agent Engine").classes(
                "text-xl font-semibold"
            )
            with ui.stepper().props("vertical flat").classes(
                "w-full"
            ) as stepper_update:
                with ui.step("Select Agent Engine"):
                    ui.label("Choose the deployed Agent Engine to update.").classes(
                        "font-semibold"
                    )
                    update_fetch_ae_button = ui.button(
                        "Fetch Agent Engines", icon="refresh"
                    )
                    update_ae_select = (
                        ui.select(
                            options={},
                            label="Agent Engine",
                            on_change=lambda e: update_details_view(e),
                        )
                        .props("outlined dense")
                        .classes("w-full mt-2")
                    )
                    update_ae_select.set_visibility(False)
                    update_fetch_ae_button.on_click(
                        lambda: fetch_agent_engines_for_update(
                            ae_project_input.value,
                            location_select.value,
                            update_ae_select,
                            update_fetch_ae_button,
                            page_state,
                        )
                    )

                with ui.step("Update Details"):
                    selected_agent_label = ui.label()
                    with ui.grid(columns=2).classes("w-full gap-4"):
                        with ui.column():
                            ui.label("Current Display Name").classes("text-lg font-semibold")
                            current_display_name_label = ui.label()
                            ui.label("Current Description").classes("text-lg font-semibold mt-4")
                            current_description_label = ui.label()
                        with ui.column():
                            ui.label("New Display Name").classes("text-lg font-semibold")
                            update_display_name_input = ui.input(
                                "Display Name"
                            ).props("outlined dense").classes("w-full")
                            ui.label("New Description").classes("text-lg font-semibold mt-4")
                            update_description_input = ui.textarea(
                                "Description"
                            ).props("outlined dense").classes("w-full")

                    with ui.stepper_navigation():
                        ui.button(
                            "Back",
                            on_click=stepper_update.previous,
                            color="gray",
                        )
                        ui.button("Next", on_click=stepper_update.next)

                with ui.step("Select Service Account"):
                    ui.label("Update the Service Account.").classes("font-semibold")
                    update_service_account_input = ui.input(
                        "Service Account"
                    ).props("outlined dense").classes("w-full")

                    with ui.stepper_navigation():
                        ui.button(
                            "Back",
                            on_click=stepper_update.previous,
                            color="gray",
                        )
                        ui.button("Next", on_click=stepper_update.next)

                with ui.step("Select Agent Configuration"):
                    ui.label(
                        "Select the Agent Configuration to apply."
                    ).classes("font-semibold")
                    update_agent_key_selection = (
                        ui.select(
                            [key for key in agent_configs.keys()],
                            label="Agent Configuration",
                        )
                        .props("outlined dense")
                        .classes("w-full")
                    )

                    update_button = ui.button(
                        "Update Agent",
                        icon="update",
                        on_click=lambda: run_actual_update(
                            ae_project_input.value,
                            location_select.value,
                            bucket_input.value,
                            page_state["update_selected_agent"],
                            agent_configs[update_agent_key_selection.value],
                            update_display_name_input.value,
                            update_description_input.value,
                            update_service_account_input.value,
                            update_status_area,
                        ),
                    )
                    update_status_area = ui.column().classes(
                        "w-full mt-2 p-2 border rounded bg-gray-50 dark:bg-gray-900 min-h-[50px]"
                    )
                    with update_status_area:
                        ui.label("Ready for update.").classes(
                            "text-sm text-gray-500"
                        )

                    with ui.stepper_navigation():
                        ui.button(
                            "Back",
                            on_click=stepper_update.previous,
                            color="gray",
                        )
                        update_button

    def _create_update_options(agents_list):
        options = {}
        for agent in agents_list:
            create_time_str = (
                agent.create_time.strftime("%Y-%m-%d %H:%M")
                if agent.create_time
                else "N/A"
            )
            update_time_str = (
                agent.update_time.strftime("%Y-%m-%d %H:%M")
                if agent.update_time
                else "N/A"
            )
            display_text = (
                f"{agent.display_name} ({agent.resource_name.split('/')[-1]}) | "
                f"Created: {create_time_str} | Updated: {update_time_str}"
            )
            options[agent.resource_name] = display_text
        return options

    async def fetch_agent_engines_for_update(
        ae_project_id: str,
        location: str,
        select_element: ui.select,
        fetch_button: ui.button,
        page_state: dict,
    ) -> None:
        fetch_button.disable()
        select_element.clear()
        select_element.set_value(None)
        page_state["update_agents"] = []
        select_element.set_visibility(False)

        existing_agents, error_msg = await _fetch_vertex_ai_resources(
            ae_project_id,
            location,
            agent_engines.list,
            ui_feedback_context={
                "button": fetch_button,
                "notify_prefix": "Agent Engines",
            },
        )

        if error_msg:
            fetch_button.enable()
            return

        if existing_agents is not None:
            page_state["update_agents"] = existing_agents

            if not existing_agents:
                ui.notify("No deployed Agent Engines found.", type="info")
                select_element.set_options([])
            else:
                options = await asyncio.to_thread(
                    _create_update_options, existing_agents
                )
                select_element.set_options(options)

            select_element.set_visibility(True)
            fetch_button.enable()
        fetch_button.enable()

    def update_details_view(selection):
        selected_agent = next((
            agent
            for agent in page_state["update_agents"]
            if agent.resource_name == selection.value
        ),
        None,
    )
        if selected_agent:
            page_state["update_selected_agent"] = selected_agent
            create_time_str = (
                selected_agent.create_time.strftime("%Y-%m-%d %H:%M")
                if selected_agent.create_time
                else "N/A"
            )
            update_time_str = (
                selected_agent.update_time.strftime("%Y-%m-%d %H:%M")
                if selected_agent.update_time
                else "N/A"
            )
            selected_agent_label.text = f"Selected Agent: {selected_agent.display_name} ({selected_agent.resource_name.split('/')[-1]}) | Created: {create_time_str} | Updated: {update_time_str}"
            current_display_name_label.text = selected_agent.display_name
            update_display_name_input.value = selected_agent.display_name
            description_str = ""
            if (
                hasattr(selected_agent, "_gca_resource")
                and hasattr(selected_agent._gca_resource, "description")
                and selected_agent._gca_resource.description
            ):
                description_str = selected_agent._gca_resource.description
            current_description_label.text = description_str
            update_description_input.value = description_str
            agent_dict = selected_agent.to_dict()
            service_account = agent_dict.get("spec", {}).get(
                "serviceAccount", "N/A (Default AE Service Acct)"
            )
            update_service_account_input.value = service_account
            stepper_update.next()

    update_ae_select.on("change", update_details_view)


async def run_actual_update(
    ae_project_id: str,
    location: str,
    bucket: str,
    agent: Any,
    agent_config: dict,
    new_display_name: str,
    new_description: str,
    new_service_account: str,
    status_area: ui.column,
) -> None:
    status_area.clear()

    timer_label = None
    stop_timer_event = asyncio.Event()

    with status_area:
        ui.label(f"Starting update for: {agent.display_name}").classes(
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
        with status_area:
            progress_label.set_text(f"Error: {init_error_msg}")
        ui.notify(
            f"Vertex AI Initialization Failed: {init_error_msg}",
            type="negative",
            multi_line=True,
            close_button=True,
        )
        return

    with status_area:
        progress_label.set_text("Vertex AI Initialized. Importing agent code...")
        ui.notify("Vertex AI Initialized Successfully.", type="positive")

    root_agent, agent_env_vars, import_error_msg = await get_agent_root_nicegui(
        agent_config
    )
    if root_agent is None:
        spinner.set_visibility(False)
        with status_area:
            progress_label.set_text(f"Error: {import_error_msg}")
        ui.notify(
            f"Agent Import Failed: {import_error_msg}",
            type="negative",
            multi_line=True,
            close_button=True,
        )
        return

    with status_area:
        progress_label.set_text("Agent code imported. Preparing update...")

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
            "Configuration ready. Updating Agent Engine (this may take 2-5 minutes)..."
        )

    start_time = time.monotonic()
    _ = asyncio.create_task(
        update_timer(start_time, timer_label, stop_timer_event, status_area)
    )
    remote_agent = None
    update_error = None
    try:

        def sync_update_agent():
            update_kwargs = {
                "agent_engine": adk_app,
                "requirements": combined_requirements,
                "extra_packages": extra_packages,
                "display_name": new_display_name,
                "description": new_description,
                "env_vars": agent_env_vars,
            }
            if new_service_account:
                update_kwargs["service_account"] = new_service_account.strip()

            return agent_engines.update(agent.resource_name, **update_kwargs)

        remote_agent = await asyncio.to_thread(sync_update_agent)
    except Exception as e:
        update_error = e
        tb_str = traceback.format_exc()
        logger.error(f"--- Agent update failed for {agent.display_name} ---\n{tb_str}")
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
            success_msg = f"Successfully updated remote agent: {remote_agent.resource_name}"
            logger.info(
                f"--- Agent update complete for {agent.display_name} ({duration_str}) --- Resource: {remote_agent.resource_name}"
            )
            with status_area:
                progress_label.set_text(
                    f"Update Successful! (Duration: {duration_str})"
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
            error_msg = f"Error during agent engine update: {update_error}"
            logger.error(
                f"Update Failed for {agent.display_name}! (Duration: {duration_str}). Error: {update_error}\nTraceback: {traceback.format_exc()}"
            )
            with status_area:
                progress_label.set_text(f"Update Failed! (Duration: {duration_str})")
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
