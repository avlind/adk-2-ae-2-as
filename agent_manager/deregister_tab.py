
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

import asyncio
import logging
from typing import Any, Dict, List, Optional

from nicegui import ui

from agent_manager.helpers import (
    deregister_agent_sync,
    fetch_agentspace_apps,
    get_all_agents_from_assistant_sync,
    get_project_number,
)

logger = logging.getLogger("WebUIManagerActivity")


def create_deregister_tab(
    page_state: Dict[str, Any],
    as_project_input: ui.input,
    agentspace_locations_select: ui.select,
) -> None:
    with ui.tab_panel("deregister"):
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("Deregister ADK Agent from Agentspace").classes(
                "text-xl font-semibold"
            )
            deregister_fetch_as_button = ui.button(
                "Fetch Agentspace Apps", icon="refresh"
            )
            deregister_as_select = ui.select(
                options={}, label="Select Agentspace App"
            ).props("outlined dense").classes("w-full mt-2")
            deregister_as_select.set_visibility(False)
            deregister_fetch_as_button.on_click(
                lambda: fetch_agentspace_apps(
                    as_project_input.value,
                    agentspace_locations_select.value,
                    deregister_as_select,
                    deregister_fetch_as_button,
                    page_state,
                    "deregister_agentspaces",
                )
            )

            with ui.card().classes("w-full mt-2"):
                ui.label("Registered ADK Agents in Selected App").classes(
                    "text-lg font-semibold"
                )
                with ui.row().classes("items-center gap-2 mb-2"):

                    async def _handle_fetch_registered_agents():
                        if (
                            page_state.get("project_id_input_timer")
                            and not page_state["project_id_input_timer"].active
                        ):
                            page_state["project_id_input_timer"] = None

                        if not page_state.get("project_id_input_timer"):
                            await _perform_project_number_update()

                        await fetch_registered_agents_async(
                            as_project_id=as_project_input.value,
                            as_project_number=page_state.get("project_number"),
                            agentspace_app=page_state.get(
                                "selected_deregister_as_app"
                            ),
                            list_container=deregister_list_container,
                            fetch_button=deregister_fetch_reg_button,
                            deregister_button=deregister_button,
                            page_state=page_state,
                        )

                    deregister_fetch_reg_button = ui.button(
                        "Fetch Registered ADK Agents",
                        icon="refresh",
                        on_click=_handle_fetch_registered_agents,
                    )
                    deregister_fetch_reg_button.bind_enabled_from(
                        deregister_as_select, "value", backward=lambda x: bool(x)
                    )
                deregister_list_container = ui.column().classes("w-full")
                with deregister_list_container:
                    ui.label(
                        "Select an Agentspace App and click 'Fetch Registered ADK Agents'."
                    ).classes("text-gray-500")
            with ui.row().classes("w-full mt-4 justify-end"):
                deregister_button = ui.button(
                    "Deregister Selected Agents",
                    color="red",
                    icon="delete",
                    on_click=lambda: confirm_and_deregister(),
                )
                deregister_button.disable()
            deregister_status_area = ui.column().classes(
                "w-full mt-2 p-2 border rounded bg-gray-50 dark:bg-gray-900 min-h-[50px]"
            )
            with deregister_status_area:
                ui.label("Ready for deregistration.").classes(
                    "text-sm text-gray-500"
                )

    async def _perform_project_number_update():
        project_id_val = as_project_input.value

        if not project_id_val:
            if page_state.get("project_number") is not None:
                logger.info(
                    "Agentspace project ID cleared. Resetting project number and dependent UI."
                )
                page_state["project_number"] = None
                page_state["_last_fetched_project_id_for_number"] = None
                await update_deregister_app_selection()
            return

        current_project_id_for_number = page_state.get(
            "_last_fetched_project_id_for_number"
        )
        if (
            project_id_val == current_project_id_for_number
            and page_state.get("project_number") is not None
        ):
            logger.debug(
                f"Project ID {project_id_val} hasn't changed and number is known. Skipping fetch of project number."
            )
            await update_deregister_app_selection()
            return

        logger.info(
            f"Fetching project number for Agentspace GCP Project ID: {project_id_val}"
        )
        page_state["project_number"] = await get_project_number(project_id_val)
        if page_state["project_number"] is not None:
            page_state["_last_fetched_project_id_for_number"] = project_id_val
        else:
            page_state["_last_fetched_project_id_for_number"] = None

        logger.info(
            f"Agentspace project number updated to: {page_state['project_number']} for project ID: {project_id_val}"
        )

        await update_deregister_app_selection()

    async def _debounced_project_id_update_action():
        await _perform_project_number_update()
        page_state["project_id_input_timer"] = None

    def handle_as_project_input_change():
        if page_state.get("project_id_input_timer"):
            page_state["project_id_input_timer"].cancel()

        if as_project_input.value and as_project_input.value.strip():
            page_state["project_id_input_timer"] = ui.timer(
                0.75, _debounced_project_id_update_action, once=True
            )
        else:
            asyncio.create_task(_perform_project_number_update())
            page_state["project_id_input_timer"] = None

    async def update_deregister_app_selection():
        selected_as_key = deregister_as_select.value
        selected_as_app = next(
            (
                app
                for app in page_state.get("deregister_agentspaces", [])
                if f"{app['location']}/{app['engine_id']}" == selected_as_key
            ),
            None,
        )
        page_state["selected_deregister_as_app"] = selected_as_app
        logger.debug(f"Deregister selected Agentspace App: {selected_as_app}")
        deregister_list_container.clear()
        with deregister_list_container:
            ui.label(
                "Select an Agentspace App and click 'Fetch Registered ADK Agents'."
            ).classes("text-gray-500")
        page_state["deregister_registered_adk_agents"] = []
        page_state["deregister_selection"] = {}
        update_deregister_button_state(page_state, deregister_button)

    async def confirm_and_deregister():
        selected_resource_names = [
            name
            for name, selected in page_state.get("deregister_selection", {}).items()
            if selected
        ]
        if not selected_resource_names:
            ui.notify("No ADK agents selected for deregistration.", type="warning")
            return
        logger.info(
            f"Confirming deregistration for agent resource names: {selected_resource_names}"
        )

        as_project = as_project_input.value
        if (
            not as_project
            or not page_state.get("project_number")
            or not page_state.get("selected_deregister_as_app")
        ):
            ui.notify(
                "Missing Agentspace Project or Agentspace App selection for deregistration.",
                type="warning",
            )
            return

        with ui.dialog() as dialog, ui.card():
            ui.label("Confirm Deregistration").classes("text-xl font-bold")
            ui.label("Permanently remove the following ADK agent registrations?")
            for resource_name in selected_resource_names:
                agent_details = next(
                    (
                        agent
                        for agent in page_state.get(
                            "deregister_registered_adk_agents", []
                        )
                        if agent.get("name") == resource_name
                    ),
                    None,
                )
                display_name = (
                    agent_details.get("displayName", resource_name.split("/")[-1])
                    if agent_details
                    else resource_name.split("/")[-1]
                )
                ui.label(f"- {display_name} (Name: ...{resource_name[-20:]})")
            ui.label(
                "This does NOT delete the underlying Agent Engine deployment."
            ).classes("mt-2")
            with ui.row().classes("mt-4 w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close, color="gray")
                ui.button(
                    "Deregister",
                    color="red",
                    on_click=lambda: run_actual_deregistration(
                        as_project, selected_resource_names, dialog
                    ),
                )
        await dialog

    async def run_actual_deregistration(
        as_project, resource_names_to_delete, dialog
    ):
        dialog.close()
        deregister_button.disable()
        with deregister_status_area:
            deregister_status_area.clear()
            ui.spinner()
            ui.label("Deregistering ADK agents...")
        logger.info(
            f"Running actual deregistration for agent resource names: {resource_names_to_delete}, AS Project: {as_project}"
        )

        success_count = 0
        fail_count = 0
        for name in resource_names_to_delete:
            success, message = await asyncio.to_thread(
                deregister_agent_sync, as_project, name
            )
            if success:
                success_count += 1
                logger.info(
                    f"Successfully deregistered {name.split('/')[-1]}. Message: {message}"
                )
                ui.notify(
                    f"Successfully deregistered {name.split('/')[-1]}.",
                    type="positive",
                )
            else:
                fail_count += 1
                logger.error(
                    f"Failed to deregister {name.split('/')[-1]}. Message: {message}"
                )
                ui.notify(
                    f"Failed to deregister {name.split('/')[-1]}: {message}",
                    type="negative",
                    multi_line=True,
                )

        with deregister_status_area:
            deregister_status_area.clear()
            summary = f"Deregistration complete. Success: {success_count}, Failed: {fail_count}."
            ui.label(summary)
            logger.info(summary)
            ui.notify(summary, type="info" if fail_count == 0 else "warning")

        await fetch_registered_agents_async(
            as_project,
            page_state.get("project_number"),
            page_state.get("selected_deregister_as_app"),
            deregister_list_container,
            deregister_fetch_reg_button,
            deregister_button,
            page_state,
        )

    as_project_input.on("update:model-value", handle_as_project_input_change)
    deregister_as_select.on(
        "update:model-value",
        lambda: asyncio.create_task(update_deregister_app_selection()),
    )


def update_deregister_button_state(current_page_state: dict, button: ui.button):
    selected_names = [
        name
        for name, selected in current_page_state.get(
            "deregister_selection", {}
        ).items()
        if selected
    ]
    button.set_enabled(bool(selected_names))


async def fetch_registered_agents_async(
    as_project_id: str,
    as_project_number: Optional[str],
    agentspace_app: Optional[Dict[str, Any]],
    list_container: ui.column,
    fetch_button: ui.button,
    deregister_button: ui.button,
    page_state: dict,
    assistant_name: str = "default_assistant",
) -> None:
    if not all([as_project_id, as_project_number, agentspace_app]):
        ui.notify(
            "Missing Agentspace Project ID, Number, or selected Agentspace App.",
            type="warning",
        )
        return
    logger.info(
        f"Fetching registered agents for deregister from Agentspace App: {agentspace_app.get('engine_id') if agentspace_app else 'N/A'} in project {as_project_id}, assistant: {assistant_name}"
    )

    fetch_button.disable()
    deregister_button.disable()
    list_container.clear()
    page_state["deregister_registered_adk_agents"] = []
    page_state["deregister_selection"] = {}
    ui.notify(
        f"Fetching all agents from assistant '{assistant_name}'...",
        type="info",
        spinner=True,
    )

    all_agents, error_msg = await asyncio.to_thread(
        get_all_agents_from_assistant_sync,
        as_project_id,
        as_project_number,
        agentspace_app,
        assistant_name,
    )

    if error_msg:
        logger.error(f"Error fetching V2 registered agents: {error_msg}")
        with list_container:
            ui.label(error_msg).classes("text-red-500")
        ui.notify(error_msg, type="negative", multi_line=True)
        fetch_button.enable()
        return

    adk_agents = [agent for agent in all_agents if "adkAgentDefinition" in agent]
    logger.info(
        f"Found {len(adk_agents)} ADK agents out of {len(all_agents)} total agents."
    )
    page_state["deregister_registered_adk_agents"] = adk_agents
    populate_deregister_list(
        adk_agents, list_container, page_state, deregister_button
    )
    fetch_button.enable()


def populate_deregister_list(
    adk_agents: List[Dict[str, Any]],
    list_container: ui.column,
    page_state: dict,
    deregister_button: ui.button,
):
    logger.debug(f"Populating deregister list with {len(adk_agents)} ADK agents.")
    with list_container:
        list_container.clear()
        if not adk_agents:
            ui.label("No ADK agents found registered in this assistant.")
            ui.notify("No ADK agents found for deregistration.", type="info")
        else:
            ui.label(f"Found {len(adk_agents)} ADK agents:").classes(
                "font-semibold"
            )
            for agent_data in adk_agents:
                agent_name = agent_data.get("name", "Unknown Name")
                display_name = agent_data.get("displayName", "N/A")
                reasoning_engine_info = (
                    agent_data.get("adkAgentDefinition", {})
                    .get("provisionedReasoningEngine", {})
                    .get("reasoningEngine", "N/A")
                )

                with ui.card().classes("w-full p-2 my-1"):
                    with ui.row().classes("items-center"):
                        checkbox = ui.checkbox().bind_value(
                            page_state["deregister_selection"], agent_name
                        ).classes("mr-2")
                        checkbox.on(
                            "update:model-value",
                            lambda: update_deregister_button_state(
                                page_state, deregister_button
                            ),
                        )
                        with ui.column().classes("gap-0"):
                            ui.label(f"{display_name}").classes("font-medium")
                            ui.label(f"Name: ...{agent_name[-30:]}").classes(
                                "text-xs text-gray-500"
                            )
                            ui.label(
                                f"Engine: {reasoning_engine_info.split('/')[-1]}"
                            ).classes("text-xs text-gray-500")
            update_deregister_button_state(page_state, deregister_button)
            ui.notify(
                f"Successfully fetched and filtered {len(adk_agents)} ADK agents.",
                type="positive",
            )
