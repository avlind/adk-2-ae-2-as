

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
from typing import Any, Dict, Optional

from nicegui import ui
from vertexai import agent_engines

from agent_manager.helpers import _fetch_vertex_ai_resources, init_vertex_ai

logger = logging.getLogger("WebUIManagerActivity")


def create_test_tab(
    page_state: Dict[str, Any],
    ae_project_input: ui.input,
    location_select: ui.select,
) -> None:
    with ui.tab_panel("test"):
        with ui.column().classes("w-full p-4 gap-4 items-stretch"):
            with ui.row().classes("items-center gap-2"):
                ui.label("Test Deployed Agent Engines").classes(
                    "text-xl font-semibold"
                )
                test_info_icon = ui.icon("info", color="primary").classes(
                    "cursor-pointer text-lg"
                )
                with ui.dialog() as test_info_dialog, ui.card():
                    ui.label("ADK Agent Engine Testing Information").classes(
                        "text-lg font-semibold mb-2"
                    )
                    ui.markdown(
                        "This is a simple testing page for your deployed Agent Engine ADK-powered Agents. This UI only supports text-in and text-out, and will not show any detailed session events such as tools calling or agent transfers. For detailed debugging of ADK agents, please use the ADK provided `adk web` in your local environment."
                    )
                    ui.button(
                        "Close", on_click=test_info_dialog.close
                    ).classes("mt-4")
                test_info_icon.on("click", test_info_dialog.open)

            with ui.card().classes("w-full p-4"):
                ui.label("1. Select Agent Engine to Test").classes(
                    "text-lg font-semibold"
                )
                with ui.row().classes("w-full items-center gap-2"):
                    test_fetch_agents_button = ui.button(
                        "Fetch Deployed Agents", icon="refresh"
                    )
                    test_agent_select = (
                        ui.select(
                            options={},
                            label="Choose Agent Engine",
                            with_input=True,
                            on_change=lambda e: handle_test_agent_selection(
                                e.value
                            ),
                        )
                        .props("outlined dense")
                        .classes("flex-grow")
                    )
                    test_agent_select.set_visibility(False)

            with ui.card().classes("w-full p-4"):
                ui.label(
                    "2. Set Username (for UI identification in test chat)"
                ).classes("text-lg font-semibold")
                ui.input(
                    "Username",
                    value=page_state["test_username"],
                    on_change=lambda e: page_state.update(
                        {"test_username": e.value}
                    ),
                ).props("outlined dense").classes("w-full")

            with ui.card().classes(
                "w-full p-4 flex flex-col grow min-h-[300px]"
            ):
                ui.label("3. Chat with Agent").classes(
                    "text-lg font-semibold mb-2"
                )
                test_chat_messages_area = ui.column().classes(
                    "w-full overflow-y-auto h-full"
                )
                with test_chat_messages_area:
                    ui.label(
                        "Select an agent and set username to begin testing."
                    ).classes("text-gray-500")

            with ui.card().classes("w-full p-4"):
                with ui.row().classes("w-full items-center gap-2"):
                    test_message_input = (
                        ui.input(placeholder="Type your message to the agent...")
                        .props("outlined dense clearable")
                        .classes("flex-grow")
                        .on(
                            "keydown.enter",
                            lambda: test_send_message_button.run_method(
                                "click"
                            ),
                        )
                    )
                    test_send_message_button = ui.button(
                        "Send",
                        icon="send",
                        on_click=lambda: handle_test_send_message(),
                    )
                    test_send_message_button.disable()

    async def fetch_agent_engines_for_test_chat():
        ae_project = ae_project_input.value
        ae_location = location_select.value
        if not ae_project or not ae_location:
            ui.notify(
                "Please set Agent Engine GCP Project ID and Location in the side configuration panel.",
                type="warning",
            )
            return

        test_agent_select.clear()
        test_agent_select.set_value(None)
        page_state["test_available_agents"] = []
        test_agent_select.set_visibility(False)
        await handle_test_agent_selection(None)

        existing_agents, error_msg = await _fetch_vertex_ai_resources(
            ae_project,
            ae_location,
            agent_engines.list,
            ui_feedback_context={
                "button": test_fetch_agents_button,
                "notify_prefix": "Agent Engines (Test)",
            },
        )

        if error_msg:
            return

        if existing_agents is not None:
            page_state["test_available_agents"] = existing_agents
            if not existing_agents:
                ui.notify(
                    "No deployed Agent Engines found for testing.", type="info"
                )
                test_agent_select.set_options([])
            else:

                def _create_test_options(agents_list):
                    return {
                        agent.resource_name: f"{agent.display_name} ({agent.resource_name.split('/')[-1]})"
                        for agent in agents_list
                    }

                options = await asyncio.to_thread(
                    _create_test_options, existing_agents
                )
                test_agent_select.set_options(options)
                ui.notify(
                    f"Found {len(existing_agents)} Agent Engines for testing.",
                    type="positive",
                )
            test_agent_select.set_visibility(True)

    test_fetch_agents_button.on_click(fetch_agent_engines_for_test_chat)

    async def handle_test_agent_selection(resource_name: Optional[str]):
        logger.info(f"Test Agent selected via UI: {resource_name}")
        page_state["test_selected_agent_resource_name"] = resource_name
        page_state["test_remote_agent_instance"] = None
        page_state["test_chat_session_id"] = None
        with test_chat_messages_area:
            test_chat_messages_area.clear()
        if resource_name:
            selected_agent_display_name = test_agent_select.options.get(
                resource_name,
                resource_name.split("/")[-1] if resource_name else "Agent",
            )
            ui.notify(
                f"Test Agent '{selected_agent_display_name}' selected. Ready to chat.",
                type="info",
            )
            test_send_message_button.set_enabled(
                not page_state["test_is_chatting"]
            )
        else:
            test_send_message_button.set_enabled(False)

    async def handle_test_send_message():
        user_message_text = test_message_input.value
        if not user_message_text or not user_message_text.strip():
            ui.notify("Message cannot be empty for test chat.", type="warning")
            return

        if not page_state["test_selected_agent_resource_name"]:
            ui.notify(
                "Please select an Agent Engine for testing first.", type="warning"
            )
            return

        page_state["test_is_chatting"] = True
        test_send_message_button.set_enabled(False)

        with test_chat_messages_area:
            ui.chat_message(
                user_message_text, name=page_state["test_username"], sent=True
            )
        test_message_input.set_value(None)

        agent_display_name = "Agent"
        if page_state["test_selected_agent_resource_name"]:
            agent_display_name = test_agent_select.options.get(
                page_state["test_selected_agent_resource_name"],
                page_state["test_selected_agent_resource_name"].split("/")[-1],
            )

        thinking_message_container = None
        with test_chat_messages_area:
            thinking_message_container = ui.chat_message(
                name=agent_display_name, stamp="typing..."
            )

        try:
            current_ae_project = ae_project_input.value
            current_ae_location = location_select.value

            if (
                not page_state["test_remote_agent_instance"]
                or not page_state["test_chat_session_id"]
            ):
                logger.info(
                    f"Initializing connection to test agent: {page_state['test_selected_agent_resource_name']}"
                )

                init_ok, init_msg = await asyncio.to_thread(
                    init_vertex_ai, current_ae_project, current_ae_location
                )
                if not init_ok:
                    ui.notify(
                        f"Failed to initialize Vertex AI for test: {init_msg}",
                        type="negative",
                    )
                    if thinking_message_container:
                        thinking_message_container.delete()
                    raise Exception(f"Vertex AI Init Failed for test: {init_msg}")

                def get_agent_sync_test():
                    return agent_engines.get(
                        resource_name=page_state[
                            "test_selected_agent_resource_name"
                        ]
                    )

                remote_agent = await asyncio.to_thread(get_agent_sync_test)
                page_state["test_remote_agent_instance"] = remote_agent

                def create_session_sync_test():
                    if page_state["test_remote_agent_instance"]:
                        return page_state[
                            "test_remote_agent_instance"
                        ].create_session(user_id=page_state["test_username"])
                    raise Exception(
                        "Test remote agent instance became unavailable before session creation."
                    )

                session_object = await asyncio.to_thread(create_session_sync_test)
                if isinstance(session_object, dict) and "id" in session_object:
                    page_state["test_chat_session_id"] = session_object["id"]
                    logger.info(
                        f"Created new test session ID: {page_state['test_chat_session_id']} for agent {page_state['test_selected_agent_resource_name']}"
                    )
                else:
                    logger.error(
                        f"Failed to extract test session ID from session object: {session_object}"
                    )
                    ui.notify(
                        f"Error: Could not obtain a valid test session ID. Response: {str(session_object)[:200]}",
                        type="negative",
                        multi_line=True,
                    )
                    if thinking_message_container:
                        thinking_message_container.delete()
                    raise Exception(
                        f"Could not obtain valid test session ID. Response: {session_object}"
                    )
                ui.notify(
                    "Connected to test agent and session started.", type="positive"
                )

            logger.info(
                f"Sending message to test agent: '{user_message_text}', session: {page_state['test_chat_session_id']}"
            )

            def stream_and_aggregate_agent_response_sync_test():
                agent_instance = page_state["test_remote_agent_instance"]
                if not agent_instance:
                    raise Exception("Test remote agent instance not available.")

                full_response_parts, all_events_received = [], []
                for event in agent_instance.stream_query(
                    message=user_message_text,
                    session_id=page_state["test_chat_session_id"],
                    user_id=page_state["test_username"],
                ):
                    all_events_received.append(event)
                    event_content = event.get("content")
                    if (
                        isinstance(event_content, dict)
                        and event_content.get("role") == "model"
                    ):
                        for part in event_content.get("parts", []):
                            if "text" in part and part["text"]:
                                full_response_parts.append(part["text"])
                    elif event.get("role") == "model":
                        for part in event.get("parts", []):
                            if "text" in part and part["text"]:
                                full_response_parts.append(part["text"])
                if not full_response_parts:
                    logger.warning(
                        f"Test agent stream_query no text parts. Events: {all_events_received}"
                    )
                    return "Agent did not return a textual response."
                return "".join(full_response_parts)

            agent_response_text = await asyncio.to_thread(
                stream_and_aggregate_agent_response_sync_test
            )
            logger.info(f"Aggregated test agent response: {agent_response_text}")
            if thinking_message_container:
                thinking_message_container.delete()
            with test_chat_messages_area:
                ui.chat_message(
                    str(agent_response_text), name=agent_display_name, sent=False
                )
        except Exception as e:
            logger.error(f"Error during test chat: {e}\n{traceback.format_exc()}")
            ui.notify(
                f"Test Chat Error: {e}",
                type="negative",
                multi_line=True,
                close_button=True,
            )
            if thinking_message_container:
                try:
                    thinking_message_container.delete()
                except Exception as del_e:
                    logger.warning(f"Could not delete test thinking message: {del_e}")
            with test_chat_messages_area:
                ui.chat_message(
                    f"Error: {str(e)[:100]}...",
                    name="System",
                    sent=False,
                    stamp="Error",
                )
        finally:
            page_state["test_is_chatting"] = False
            test_send_message_button.set_enabled(
                bool(page_state["test_selected_agent_resource_name"])
            )
