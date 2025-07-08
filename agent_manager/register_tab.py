

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
from typing import Any, Dict

from nicegui import ui
from vertexai import agent_engines

from agent_manager.helpers import (
    _fetch_vertex_ai_resources,
    fetch_agentspace_apps,
    get_project_number,
    register_agent_sync,
)

logger = logging.getLogger("WebUIManagerActivity")


def create_register_tab(
    page_state: Dict[str, Any],
    ae_project_input: ui.input,
    location_select: ui.select,
    as_project_input: ui.input,
    agentspace_locations_select: ui.select,
    agent_configs: Dict[str, Any],
) -> None:
    with ui.tab_panel("register"):
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("Register Agent Engine with Agentspace").classes(
                "text-xl font-semibold"
            )
            with ui.stepper().props("vertical flat").classes(
                "w-full"
            ) as stepper_register:
                with ui.step("Select Agent Engine"):
                    ui.label("Choose the deployed Agent Engine to register.")
                    register_fetch_ae_button = ui.button(
                        "Fetch Agent Engines", icon="refresh"
                    )
                    register_ae_select = ui.select(
                        options={}, label="Agent Engine"
                    ).props("outlined dense").classes("w-full mt-2")
                    register_ae_select.set_visibility(False)
                    with ui.stepper_navigation():
                        register_next_button_step1 = ui.button(
                            "Next", on_click=stepper_register.next
                        )
                        register_next_button_step1.bind_enabled_from(
                            register_ae_select, "value"
                        )
                    register_fetch_ae_button.on_click(
                        lambda: fetch_agent_engines_for_register(
                            ae_project_input.value,
                            location_select.value,
                            register_ae_select,
                            register_fetch_ae_button,
                            page_state,
                            register_next_button_step1,
                        )
                    )

                with ui.step("Select Agentspace App"):
                    ui.label(
                        "Choose the Agentspace App (Discovery Engine App ID)."
                    )
                    register_fetch_as_button = ui.button(
                        "Fetch Agentspace Apps", icon="refresh"
                    )
                    register_as_select = ui.select(
                        options={}, label="Agentspace App"
                    ).props("outlined dense").classes("w-full mt-2")
                    register_as_select.set_visibility(False)
                    with ui.stepper_navigation():
                        ui.button(
                            "Back",
                            on_click=stepper_register.previous,
                            color="gray",
                        )
                        register_next_button_step2 = ui.button(
                            "Next", on_click=stepper_register.next
                        )
                        register_next_button_step2.bind_enabled_from(
                            register_as_select, "value"
                        )
                    register_fetch_as_button.on_click(
                        lambda: fetch_agentspace_apps(
                            as_project_input.value,
                            agentspace_locations_select.value,
                            register_as_select,
                            register_fetch_as_button,
                            page_state,
                            "register_agentspaces",
                        )
                    )

                with ui.step("Configure & Register"):
                    ui.label(
                        "Provide details for the new agent registration."
                    ).classes("font-semibold")
                    register_display_name_input = ui.input(
                        "Display Name"
                    ).props("outlined dense").classes("w-full")
                    register_description_input = ui.textarea(
                        "Description (General)"
                    ).props("outlined dense").classes("w-full")
                    register_tool_description_input = ui.textarea(
                        "Tool Description (Prompt for LLM)"
                    ).props("outlined dense").classes("w-full")
                    register_icon_input = ui.input(
                        "Icon URI (optional)",
                        value="https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg",
                    ).props("outlined dense").classes("w-full")

                    ui.label("Authorizations (Optional)").classes(
                        "text-md font-medium mt-3 mb-1"
                    )
                    ui.label(
                        "Add full resource names for each OAuth 2.0 authorization required by the agent."
                    ).classes("text-xs text-gray-500 mb-2")
                    direct_auth_inputs_container = ui.column().classes(
                        "w-full gap-1"
                    )

                    @ui.refreshable
                    def render_register_auth_inputs():
                        direct_auth_inputs_container.clear()
                        current_auths = page_state.get(
                            "register_authorizations_list", []
                        )
                        with direct_auth_inputs_container:
                            if not current_auths:
                                ui.label(
                                    "No authorizations added yet."
                                ).classes("text-xs text-gray-400")
                            for i, auth_value in enumerate(current_auths):
                                with ui.row().classes(
                                    "w-full items-center no-wrap"
                                ):
                                    ui.input(
                                        label=f"Auth #{i+1}",
                                        value=auth_value,
                                        placeholder="projects/PROJECT_ID/locations/global/authorizations/AUTH_ID",
                                        on_change=lambda e, index=i: page_state[
                                            "register_authorizations_list"
                                        ].__setitem__(index, e.value),
                                    ).props(
                                        "outlined dense clearable"
                                    ).classes(
                                        "flex-grow"
                                    )
                                    ui.button(
                                        icon="remove_circle_outline",
                                        on_click=lambda _, index=i: (
                                            page_state[
                                                "register_authorizations_list"
                                            ].pop(index),
                                            render_register_auth_inputs.refresh(),
                                        ),
                                    ).props(
                                        "flat color=negative dense"
                                    ).tooltip(
                                        "Remove this authorization"
                                    )

                    render_register_auth_inputs()
                    ui.button(
                        "Add Authorization",
                        icon="add",
                        on_click=lambda: (
                            page_state.setdefault(
                                "register_authorizations_list", []
                            ).append(""),
                            render_register_auth_inputs.refresh(),
                        ),
                    ).classes("mt-2 self-start")

                    async def update_register_defaults():
                        selected_ae_resource = register_ae_select.value
                        selected_ae = next(
                            (
                                ae
                                for ae in page_state.get(
                                    "register_agent_engines", []
                                )
                                if ae.resource_name == selected_ae_resource
                            ),
                            None,
                        )
                        if selected_ae:
                            config_match = next(
                                (
                                    cfg
                                    for cfg_key, cfg in agent_configs.items()
                                    if isinstance(cfg, dict)
                                    and cfg.get("ae_display_name")
                                    == selected_ae.display_name
                                ),
                                None,
                            )
                            if config_match:
                                register_display_name_input.value = (
                                    config_match.get(
                                        "as_display_name",
                                        selected_ae.display_name,
                                    )
                                )
                                default_desc = config_match.get(
                                    "description",
                                    f"Agent: {selected_ae.display_name}",
                                )
                                register_description_input.value = default_desc
                                register_tool_description_input.value = (
                                    config_match.get(
                                        "as_tool_description", default_desc
                                    )
                                )
                                register_icon_input.value = config_match.get(
                                    "as_uri",
                                    "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg",
                                )
                            else:
                                register_display_name_input.value = (
                                    selected_ae.display_name
                                )
                                default_desc = (
                                    f"Agent: {selected_ae.display_name}"
                                )
                                register_description_input.value = default_desc
                                register_tool_description_input.value = (
                                    default_desc
                                )
                                register_icon_input.value = "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"
                        page_state["register_authorizations_list"] = []
                        render_register_auth_inputs.refresh()

                    ui.timer(0.1, update_register_defaults, once=True)
                    register_ae_select.on(
                        "update:model-value", update_register_defaults
                    )

                    register_button = ui.button(
                        "Register Agent",
                        icon="app_registration",
                        on_click=lambda: start_registration(),
                    )
                    register_status_area = ui.column().classes(
                        "w-full mt-2 p-2 border rounded bg-gray-50 dark:bg-gray-900 min-h-[50px]"
                    )
                    with register_status_area:
                        ui.label("Ready for registration.").classes(
                            "text-sm text-gray-500"
                        )
                    with ui.stepper_navigation():
                        ui.button(
                            "Back",
                            on_click=stepper_register.previous,
                            color="gray",
                        )

    async def fetch_agent_engines_for_register(
        ae_project_id: str,
        location: str,
        select_element: ui.select,
        fetch_button: ui.button,
        page_state: dict,
        next_button: ui.button,
    ) -> None:
        next_button.disable()
        fetch_button.disable()
        select_element.clear()
        select_element.set_value(None)
        page_state["register_agent_engines"] = []
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
            page_state["register_agent_engines"] = existing_agents

            if not existing_agents:
                ui.notify("No deployed Agent Engines found.", type="info")
                logger.info(
                    f"No deployed Agent Engines found in {ae_project_id}/{location} for registration."
                )
                select_element.set_options([])
            else:

                def _create_register_options(agents_list):
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

                options = await asyncio.to_thread(
                    _create_register_options, existing_agents
                )

                select_element.set_options(options)
                logger.info(
                    f"Found {len(existing_agents)} Agent Engines in {ae_project_id}/{location} for registration."
                )

            select_element.set_visibility(True)
            fetch_button.enable()
        fetch_button.enable()

    async def start_registration():
        as_project = as_project_input.value
        as_project_num = await get_project_number(as_project)
        selected_ae_resource = register_ae_select.value
        selected_as_key = register_as_select.value

        display_name = register_display_name_input.value
        description = register_description_input.value
        tool_description = register_tool_description_input.value
        icon_uri = register_icon_input.value

        authorizations_list_from_state = page_state.get(
            "register_authorizations_list", []
        )
        authorizations_list_for_api = [
            auth.strip()
            for auth in authorizations_list_from_state
            if auth and auth.strip()
        ]

        if not all(
            [
                as_project,
                as_project_num,
                selected_ae_resource,
                selected_as_key,
                display_name,
                description,
                tool_description,
            ]
        ):
            ui.notify(
                "Missing required fields for registration (Agentspace Project, Engine, App, names/desc). Please check inputs.",
                type="warning",
            )
            return
        logger.info(
            f"Starting registration. AS Project: {as_project}, AE Resource: {selected_ae_resource}, AS App Key: {selected_as_key}, Display Name: {display_name}, Authorizations: {authorizations_list_for_api}"
        )

        selected_as_app = next(
            (
                app
                for app in page_state.get("register_agentspaces", [])
                if f"{app['location']}/{app['engine_id']}" == selected_as_key
            ),
            None,
        )
        if not selected_as_app:
            ui.notify(
                "Internal Error: Could not find selected Agentspace App details.",
                type="negative",
            )
            return

        register_button.disable()
        with register_status_area:
            register_status_area.clear()
            ui.label("Registering agent...")
            ui.spinner()

        success, message = await asyncio.to_thread(
            register_agent_sync,
            as_project,
            as_project_num,
            selected_as_app,
            selected_ae_resource,
            display_name,
            description,
            tool_description,
            icon_uri,
            authorizations_list_for_api,
        )

        with register_status_area:
            register_status_area.clear()
            if success:
                ui.html(
                    f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>"
                )
                logger.info(f"Registration successful: {message}")
                ui.notify(
                    "Agent registered successfully!",
                    type="positive",
                    multi_line=True,
                    close_button=True,
                )
            else:
                error_summary = (
                    message.splitlines()[0] if message else "Unknown error"
                )
                ui.html(
                    f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>"
                )
                logger.error(f"Registration failed: {message}")
                ui.notify(
                    f"Failed to register agent: {error_summary}",
                    type="negative",
                    multi_line=True,
                    close_button=True,
                )
        register_button.enable()
