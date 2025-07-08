
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
from typing import Any, Dict

from nicegui import ui

from agent_manager.helpers import (
    AS_AUTH_DEFAULT_LOCATION,
    create_authorization_sync_webui,
    delete_authorization_sync_webui,
    get_access_token_and_credentials_async_webui,
    get_project_number,
    list_authorizations_sync_webui,
)

logger = logging.getLogger("WebUIManagerActivity")


def create_auth_tab(page_state: Dict[str, Any], as_project_input: ui.input) -> None:
    with ui.tab_panel("agentspace_auth"):
        with ui.column().classes("w-full p-4 gap-4"):
            ui.label("Manage Agentspace OAuth Authorizations").classes(
                "text-xl font-semibold"
            )
            ui.label(
                f"Authorizations are managed at the '{AS_AUTH_DEFAULT_LOCATION}' location and are collectively scoped project-wide."
            ).classes("text-sm text-gray-500 mb-3")

            with ui.tabs().classes("w-full") as auth_sub_tabs:
                auth_manage_tab_btn = ui.tab("Manage Authorizations", icon="list")
                auth_create_tab_btn = ui.tab(
                    "Create Authorization", icon="add_circle_outline"
                )

            with ui.tab_panels(
                auth_sub_tabs, value=auth_manage_tab_btn
            ).classes("w-full mt-4"):
                with ui.tab_panel(auth_create_tab_btn):
                    with ui.column().classes("w-full gap-3"):
                        auth_id_create_input_el = ui.input(
                            "Authorization ID",
                            placeholder="e.g., my-google-oauth-client",
                        ).props("outlined dense clearable").classes("w-full")
                        auth_client_id_input_el = ui.input(
                            "OAuth Client ID"
                        ).props("outlined dense clearable").classes("w-full")
                        auth_client_secret_input_el = ui.input(
                            "OAuth Client Secret",
                            password=True,
                            password_toggle_button=True,
                        ).props("outlined dense clearable").classes("w-full")
                        auth_uri_input_el = ui.input(
                            "OAuth Authorization URI",
                            placeholder="https://accounts.google.com/o/oauth2/v2/auth",
                        ).props("outlined dense clearable").classes("w-full")
                        auth_token_uri_input_el = ui.input(
                            "OAuth Token URI",
                            placeholder="https://oauth2.googleapis.com/token",
                        ).props("outlined dense clearable").classes("w-full")
                        auth_create_status_area = ui.column().classes(
                            "w-full mt-3 p-3 border rounded bg-gray-50 dark:bg-gray-800 min-h-[60px]"
                        )
                        with auth_create_status_area:
                            ui.label(
                                "Fill in details and click 'Create Authorization'."
                            ).classes("text-sm text-gray-500")
                        auth_create_button_el = ui.button(
                            "Create Authorization", icon="save"
                        )

                        async def _handle_create_authorization():
                            target_project_id = as_project_input.value
                            auth_id = auth_id_create_input_el.value
                            client_id = auth_client_id_input_el.value
                            client_secret = auth_client_secret_input_el.value
                            auth_uri = auth_uri_input_el.value
                            token_uri = auth_token_uri_input_el.value

                            if not all(
                                [
                                    target_project_id,
                                    auth_id,
                                    client_id,
                                    client_secret,
                                    auth_uri,
                                    token_uri,
                                ]
                            ):
                                ui.notify(
                                    "All fields are required for authorization creation. Please check inputs.",
                                    type="warning",
                                )
                                return

                            auth_create_button_el.disable()
                            with auth_create_status_area:
                                auth_create_status_area.clear()
                                with ui.row().classes("items-center"):
                                    ui.spinner(size="lg").classes("mr-2")
                                    ui.label(
                                        "Attempting to create authorization..."
                                    )

                            (
                                access_token,
                                _,
                                token_error,
                            ) = await get_access_token_and_credentials_async_webui()
                            if token_error or not access_token:
                                with auth_create_status_area:
                                    auth_create_status_area.clear()
                                    ui.label(
                                        f"Error getting access token: {token_error or 'Unknown error'}"
                                    ).classes("text-red-600")
                                ui.notify(
                                    f"Access Token Error: {token_error or 'Unknown error'}",
                                    type="negative",
                                    multi_line=True,
                                )
                                auth_create_button_el.enable()
                                return

                            target_project_number = await get_project_number(
                                target_project_id
                            )
                            if not target_project_number:
                                with auth_create_status_area:
                                    auth_create_status_area.clear()
                                    ui.label(
                                        f"Error getting project number for {target_project_id}."
                                    ).classes("text-red-600")
                                ui.notify(
                                    f"Project Number Error for {target_project_id}.",
                                    type="negative",
                                    multi_line=True,
                                )
                                auth_create_button_el.enable()
                                return

                            success, message = await asyncio.to_thread(
                                create_authorization_sync_webui,
                                target_project_id,
                                target_project_number,
                                auth_id,
                                client_id,
                                client_secret,
                                auth_uri,
                                token_uri,
                                access_token,
                            )

                            with auth_create_status_area:
                                auth_create_status_area.clear()
                                if success:
                                    ui.html(
                                        f"<span class='text-green-600'>Success:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>"
                                    )
                                    ui.notify(
                                        "Authorization created successfully!",
                                        type="positive",
                                        multi_line=True,
                                    )
                                    auth_id_create_input_el.set_value("")
                                    auth_client_id_input_el.set_value("")
                                    auth_client_secret_input_el.set_value("")
                                    auth_uri_input_el.set_value("")
                                    auth_token_uri_input_el.set_value("")
                                else:
                                    ui.html(
                                        f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{message}</pre>"
                                    )
                                    ui.notify(
                                        "Failed to create authorization.",
                                        type="negative",
                                        multi_line=True,
                                    )
                            auth_create_button_el.enable()

                        auth_create_button_el.on_click(
                            _handle_create_authorization
                        )

                with ui.tab_panel(auth_manage_tab_btn):
                    with ui.column().classes("w-full gap-3"):
                        auth_list_status_area = ui.column().classes(
                            "w-full mt-3 p-3 border rounded bg-gray-50 dark:bg-gray-800 min-h-[60px]"
                        )
                        with auth_list_status_area:
                            ui.label(
                                "Click 'List Authorizations' to see all OAuth credentials."
                            ).classes("text-sm text-gray-500")
                        auth_list_button_el = ui.button(
                            "List Authorizations", icon="refresh"
                        )
                        auth_list_results_area = ui.column().classes("w-full mt-4")

                        async def _handle_list_authorizations():
                            target_project_id = as_project_input.value
                            if not target_project_id:
                                ui.notify(
                                    "Agentspace Project ID is required.",
                                    type="warning",
                                )
                                return

                            auth_list_button_el.disable()
                            auth_list_results_area.clear()
                            with auth_list_status_area:
                                auth_list_status_area.clear()
                                with ui.row().classes("items-center"):
                                    ui.spinner(size="lg").classes("mr-2")
                                    ui.label("Attempting to list authorizations...")

                            (
                                access_token,
                                _,
                                token_error,
                            ) = await get_access_token_and_credentials_async_webui()
                            if token_error or not access_token:
                                with auth_list_status_area:
                                    auth_list_status_area.clear()
                                    ui.label(
                                        f"Error getting access token: {token_error or 'Unknown error'}"
                                    ).classes("text-red-600")
                                ui.notify(
                                    f"Access Token Error: {token_error or 'Unknown error'}",
                                    type="negative",
                                    multi_line=True,
                                )
                                auth_list_button_el.enable()
                                return

                            target_project_number = await get_project_number(
                                target_project_id
                            )
                            if not target_project_number:
                                with auth_list_status_area:
                                    auth_list_status_area.clear()
                                    ui.label(
                                        f"Error getting project number for {target_project_id}."
                                    ).classes("text-red-600")
                                ui.notify(
                                    f"Project Number Error for {target_project_id}.",
                                    type="negative",
                                    multi_line=True,
                                )
                                auth_list_button_el.enable()
                                return

                            success, result = await asyncio.to_thread(
                                list_authorizations_sync_webui,
                                target_project_id,
                                target_project_number,
                                access_token,
                            )

                            with auth_list_status_area:
                                auth_list_status_area.clear()
                                if success:
                                    ui.label("Successfully listed authorizations.").classes("text-green-600")
                                    if isinstance(result, list) and result:
                                        with auth_list_results_area:

                                            async def _run_actual_auth_deletion_webui(target_project_id: str, auth_id: str):
                                                (
                                                    access_token,
                                                    _,
                                                    token_error,
                                                ) = await get_access_token_and_credentials_async_webui()
                                                if token_error or not access_token:
                                                    with auth_list_results_area:
                                                        ui.notify(f"Access Token Error: {token_error or 'Unknown'}", type="negative")
                                                    return

                                                target_project_number = await get_project_number(target_project_id)
                                                if not target_project_number:
                                                    with auth_list_results_area:
                                                        ui.notify(f"Project Number Error for {target_project_id}.", type="negative")
                                                    return

                                                (success, message) = await asyncio.to_thread(
                                                    delete_authorization_sync_webui,
                                                    target_project_id,
                                                    target_project_number,
                                                    auth_id,
                                                    access_token,
                                                )
                                                if success:
                                                    with auth_list_results_area:
                                                        ui.notify("Authorization deleted!", type="positive")
                                                        await _handle_list_authorizations() # Refresh list
                                                else:
                                                    with auth_list_results_area:
                                                        ui.notify(f"Deletion failed: {message}", type="negative", multi_line=True)

                                            async def show_delete_confirmation(auth_id: str):
                                                target_project_id = as_project_input.value
                                                with ui.dialog() as confirm_dialog, ui.card():
                                                    ui.label(f"Are you sure you want to delete authorization '{auth_id}' from project '{target_project_id}'?").classes("text-lg mb-2")
                                                    ui.label("This action cannot be undone.").classes("font-semibold text-red-600")
                                                    with ui.row().classes("mt-5 w-full justify-end gap-2"):
                                                        ui.button("Cancel", on_click=confirm_dialog.close, color="gray")
                                                        ui.button(
                                                            "Delete Permanently",
                                                            on_click=lambda: (
                                                                confirm_dialog.close(),
                                                                asyncio.create_task(
                                                                    _run_actual_auth_deletion_webui(target_project_id, auth_id)
                                                                )
                                                            ),
                                                            color="red",
                                                        )
                                                await confirm_dialog

                                            columns = [
                                                    {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left', 'sortable': True},
                                                    {'name': 'clientId', 'label': 'Client ID', 'field': 'clientId', 'align': 'left'},
                                                    {'name': 'authUri', 'label': 'Auth URI', 'field': 'authUri', 'align': 'left'},
                                                    {'name': 'tokenUri', 'label': 'Token URI', 'field': 'tokenUri', 'align': 'left'},
                                                    {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'align': 'right'},
                                                ]
                                            rows = [
                                                {
                                                    'name': auth.get('name', '').split('/')[-1],
                                                    'clientId': auth.get('serverSideOauth2', {}).get('clientId', 'N/A'),
                                                    'authUri': auth.get('serverSideOauth2', {}).get('authorizationUri', 'N/A'),
                                                    'tokenUri': auth.get('serverSideOauth2', {}).get('tokenUri', 'N/A'),
                                                } for auth in result
                                            ]
                                            auth_table = ui.table(columns=columns, rows=rows, row_key='name').classes('w-full')
                                            auth_table.add_slot('body-cell-actions', '''
                                                <q-td :props="props">
                                                    <q-btn @click="$parent.$emit('delete', props.row.name)" icon="delete" color="red" flat dense round />
                                                </q-td>
                                            ''')
                                            auth_table.on('delete', lambda e: show_delete_confirmation(e.args))
                                    else:
                                        with auth_list_results_area:
                                            ui.label("No authorizations found.").classes("text-gray-500")

                                else:
                                    ui.html(
                                        f"<span class='text-red-600'>Error:</span><pre class='mt-1 text-xs whitespace-pre-wrap'>{result}</pre>"
                                    )
                                    ui.notify(
                                        "Failed to list authorizations.",
                                        type="negative",
                                        multi_line=True,
                                    )
                            auth_list_button_el.enable()

                        auth_list_button_el.on_click(_handle_list_authorizations)
