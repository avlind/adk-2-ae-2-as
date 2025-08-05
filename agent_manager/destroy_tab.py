

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
import traceback
from typing import Any, Dict, List

from nicegui import ui
from vertexai import agent_engines

from agent_manager.helpers import _fetch_vertex_ai_resources, init_vertex_ai

logger = logging.getLogger("WebUIManagerActivity")


def create_destroy_tab(
    page_state: Dict[str, Any],
    ae_project_input: ui.input,
    location_select: ui.select,
) -> None:
    with ui.tab_panel("destroy"):
        with ui.column().classes("w-full p-4 gap-4"):
            fetch_destroy_button = ui.button(
                "Fetch Existing Agent Engines",
                icon="refresh",
                on_click=lambda: fetch_agents_for_destroy(
                    ae_project_input.value,
                    location_select.value,
                    destroy_list_container,
                    destroy_delete_button,
                    fetch_destroy_button,
                    page_state,
                ),
            )
            with ui.card().classes("w-full mt-2"):
                ui.label("Your Agent Engines").classes("text-lg font-semibold")
                destroy_list_container = ui.column().classes("w-full")
                with destroy_list_container:
                    ui.label("Click 'Fetch Existing Agent Engines'.").classes(
                        "text-gray-500"
                    )
            with ui.row().classes("w-full mt-4 justify-end"):
                destroy_delete_button = ui.button(
                    "Delete Selected Agents",
                    color="red",
                    icon="delete_forever",
                    on_click=lambda: confirm_and_delete_agents(
                        ae_project_input.value, location_select.value, page_state
                    ),
                )
                destroy_delete_button.disable()


async def fetch_agents_for_destroy(
    ae_project_id: str,
    location: str,
    list_container: ui.column,
    delete_button: ui.button,
    fetch_button: ui.button,
    page_state: dict,
) -> None:
    fetch_button.disable()
    list_container.clear()
    page_state["destroy_agents"] = []
    page_state["destroy_selected"] = {}
    delete_button.disable()

    with list_container:
        ui.label("Fetching Agent Engines...").classes("text-gray-500")

    existing_agents, error_msg = await _fetch_vertex_ai_resources(
        ae_project_id,
        location,
        agent_engines.list,
        ui_feedback_context={
            "button": fetch_button,
            "container": list_container,
            "notify_prefix": "Agent Engines",
        },
    )

    list_container.clear()
    if error_msg:
        fetch_button.enable()
        return
    if existing_agents is not None:
        if not existing_agents:
            page_state["destroy_agents"] = []
            with list_container:
                ui.label("0 Available Agent Engines").classes(
                    "text-lg font-semibold mb-2"
                )
                ui.label(f"No agent engines found in {ae_project_id}/{location}.")
            ui.notify("No agent engines found.", type="info")
        else:
            page_state["destroy_agents"] = existing_agents

            def _prepare_destroy_list_details(agents_list):
                details = []
                for agent in agents_list:
                    agent_dict = agent.to_dict()
                    service_account = agent_dict.get("spec", {}).get(
                        "serviceAccount", "N/A (Default AE Service Acct)"
                    )
                    description_str = "No description."
                    if (
                        hasattr(agent, "_gca_resource")
                        and hasattr(agent._gca_resource, "description")
                        and agent._gca_resource.description
                    ):
                        description_str = agent._gca_resource.description
                    details.append(
                        {
                            "resource_name": agent.resource_name,
                            "display_name": agent.display_name,
                            "description": description_str,
                            "service_account": service_account,
                            "create_time": agent.create_time.strftime(
                                "%Y-%m-%d %H:%M:%S %Z"
                            )
                            if agent.create_time
                            else "N/A",
                            "update_time": agent.update_time.strftime(
                                "%Y-%m-%d %H:%M:%S %Z"
                            )
                            if agent.update_time
                            else "N/A",
                        }
                    )
                return details

            agent_details_list = await asyncio.to_thread(
                _prepare_destroy_list_details, existing_agents
            )

            with list_container:
                ui.label(
                    f"{len(agent_details_list)} Available Agent Engines:"
                ).classes("text-lg font-semibold mb-2")
                for agent_details in agent_details_list:
                    resource_name = agent_details["resource_name"]
                    card = ui.card().classes("w-full mb-2 p-3")
                    with card:
                        with ui.row().classes(
                            "w-full items-center justify-between"
                        ):
                            ui.label(f"{agent_details['display_name']}").classes(
                                "text-lg font-medium"
                            )
                        with ui.column().classes(
                            "gap-0 mt-1 text-sm text-gray-600 dark:text-gray-400"
                        ):
                            ui.label(f"Resource: {resource_name}")
                            ui.label(
                                f"Description: {agent_details['description']}"
                            )
                            ui.label(
                                f"Service Account: {agent_details['service_account']}"
                            )
                            with ui.row().classes("gap-4 items-center"):
                                ui.label(
                                    f"Created: {agent_details['create_time']}"
                                )
                                ui.label(
                                    f"Updated: {agent_details['update_time']}"
                                )
                        checkbox = ui.checkbox("Select for Deletion")
                        checkbox.bind_value(
                            page_state["destroy_selected"], resource_name
                        )
                        checkbox.classes("absolute top-2 right-2")
            delete_button.enable()


async def confirm_and_delete_agents(
    ae_project_id: str, location: str, page_state: dict
) -> None:
    selected_map = page_state.get("destroy_selected", {})
    agents_to_delete = [name for name, selected in selected_map.items() if selected]

    if not agents_to_delete:
        ui.notify("No agents selected for deletion.", type="warning")
        return
    logger.info(
        f"Confirmation requested for deleting agents: {agents_to_delete} from {ae_project_id}/{location}."
    )

    with ui.dialog() as dialog, ui.card():
        ui.label("Confirm Deletion").classes("text-xl font-bold")
        ui.label("You are about to permanently delete the following agent(s):")
        for name in agents_to_delete:
            agent_display = name
            for agent in page_state.get("destroy_agents", []):
                if agent.resource_name == name:
                    agent_display = (
                        f"{agent.display_name} ({name.split('/')[-1]})"
                    )
                    break
            ui.label(f"- {agent_display}")
        ui.label("\nThis action cannot be undone.").classes(
            "font-bold text-red-600"
        )

        with ui.row().classes("mt-4 w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close, color="gray")
            ui.button(
                "Delete Permanently",
                on_click=lambda: run_actual_deletion(
                    ae_project_id, location, agents_to_delete, page_state, dialog
                ),
                color="red",
            )
    await dialog


async def run_actual_deletion(
    ae_project_id: str,
    location: str,
    resource_names: List[str],
    page_state: dict,
    dialog: ui.dialog,
) -> None:
    dialog.close()

    init_success, init_error_msg = await asyncio.to_thread(
        init_vertex_ai, ae_project_id, location
    )
    logger.info(
        f"Starting actual deletion of agents: {resource_names} from {ae_project_id}/{location}."
    )
    if not init_success:
        full_msg = (
            f"Failed to re-initialize Vertex AI. Deletion aborted.\nDetails: {init_error_msg}"
            if init_error_msg
            else "Failed to re-initialize Vertex AI. Deletion aborted."
        )
        logger.error(
            f"Vertex AI re-initialization failed before deletion: {full_msg}"
        )
        ui.notify(full_msg, type="negative", multi_line=True, close_button=True)
        return

    logger.info(
        f"\n--- Deleting Selected Agents from {ae_project_id}/{location} ---"
    )
    progress_notification = ui.notification(timeout=None, close_button=False)

    success_count = 0
    fail_count = 0
    failed_agents: List[str] = []

    def delete_single_agent(resource_name_to_delete):
        agent_to_delete = agent_engines.get(
            resource_name=resource_name_to_delete
        )
        agent_to_delete.delete(force=True)

    for i, resource_name in enumerate(resource_names):
        try:
            progress_notification.message = (
                f"Deleting {i+1}/{len(resource_names)}: {resource_name.split('/')[-1]}..."
            )
            progress_notification.spinner = True
            logger.info(f"Attempting to delete agent: {resource_name}")
            await asyncio.to_thread(delete_single_agent, resource_name)
            logger.info(f"Successfully deleted agent: {resource_name}")
            ui.notify(
                f"Successfully deleted {resource_name.split('/')[-1]}",
                type="positive",
            )
            success_count += 1
            if resource_name in page_state.get("destroy_selected", {}):
                del page_state["destroy_selected"][resource_name]
            page_state["destroy_agents"] = [
                a
                for a in page_state.get("destroy_agents", [])
                if a.resource_name != resource_name
            ]

        except Exception as e:
            error_msg = f"Failed to delete {resource_name.split('/')[-1]}: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            ui.notify(
                error_msg, type="negative", multi_line=True, close_button=True
            )
            fail_count += 1
            failed_agents.append(resource_name)
        finally:
            progress_notification.spinner = False

    progress_notification.dismiss()
    logger.info(
        f"--- Deletion process finished for {ae_project_id}/{location}. Success: {success_count}, Fail: {fail_count} ---"
    )

    summary_title = (
        "Deletion Complete"
        if fail_count == 0
        else "Deletion Finished with Errors"
    )
    with ui.dialog() as summary_dialog, ui.card():
        ui.label(summary_title).classes("text-xl font-bold")
        ui.label(f"Successfully deleted: {success_count}")
        ui.label(f"Failed to delete: {fail_count}")
        if failed_agents:
            ui.label("Failed agents:")
            for name in failed_agents:
                ui.label(f"- {name.split('/')[-1]}")
        with ui.row().classes("mt-4 w-full justify-end"):
            ui.button("OK", on_click=summary_dialog.close)
    await summary_dialog
