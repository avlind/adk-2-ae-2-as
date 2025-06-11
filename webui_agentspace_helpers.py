#  Copyright (C) 2025 Google LLC
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import json
import logging
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

import google.auth
import google.auth.transport.requests
import requests

logger = logging.getLogger(__name__) # Use module-level logger

# --- Legacy Agentspace API Helpers ---

def register_agent_with_agentspace_sync(
    as_project_id: str, as_project_number: str,
    agentspace_app: Dict[str, Any],
    agent_engine_resource_name: str, agent_display_name: str, agent_description: str,
    agent_icon_uri: str, default_assistant_name: str = "default_assistant"
) -> Tuple[bool, str]:
    """Synchronous function to register Agent Engine with Agentspace App (Legacy API)."""
    logger.info(f"Legacy Register: AS Project: {as_project_id} (Num: {as_project_number}), App: {agentspace_app['engine_id']}, AE: {agent_engine_resource_name}")
    agentspace_app_id = agentspace_app['engine_id']
    agentspace_location = agentspace_app['location']

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh token from ADC for legacy registration.")
            raise ValueError("Failed to refresh token from ADC.")
        access_token = credentials.token

        agent_id = re.sub(r'\W+', '_', agent_display_name.lower())[:50]
        hostname = f"{agentspace_location}-discoveryengine.googleapis.com" if agentspace_location != "global" else "discoveryengine.googleapis.com"
        assistant_api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{agentspace_location}/collections/default_collection/engines/{agentspace_app_id}/assistants/{default_assistant_name}"

        common_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-goog-user-project": as_project_id,
        }

        new_agent_config_payload = {
            "id": agent_id,
            "displayName": agent_display_name,
            "vertexAiSdkAgentConnectionInfo": {"reasoningEngine": agent_engine_resource_name},
            "toolDescription": agent_description,
            "icon": {"uri": agent_icon_uri if agent_icon_uri and agent_icon_uri != "n/a" else "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"},
        }

        get_response = requests.get(assistant_api_endpoint, headers=common_headers)
        existing_agent_configs = []
        try:
            get_response.raise_for_status()
            current_config = get_response.json()
            existing_agent_configs = current_config.get("agentConfigs", [])
        except requests.exceptions.RequestException as e:
            if e.response is not None and e.response.status_code == 404:
                logger.info(f"Assistant '{default_assistant_name}' not found (Legacy). Will create it.")
            else:
                raise ValueError(f"Error fetching current assistant config: {e.response.text if e.response else str(e)}") from e

        updated_configs = [cfg for cfg in existing_agent_configs if cfg.get("id") != agent_id]
        updated_configs.append(new_agent_config_payload)
        patch_payload = {"agentConfigs": updated_configs}
        patch_endpoint_with_mask = f"{assistant_api_endpoint}?updateMask=agent_configs"
        
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in common_headers.items()}
        logger.debug(f"LEGACY_REGISTER_REQUEST:\nURL: {patch_endpoint_with_mask}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(patch_payload, indent=2)}")

        response = requests.patch(patch_endpoint_with_mask, headers=common_headers, data=json.dumps(patch_payload))
        response.raise_for_status()
        logger.info("Successfully registered agent with Agentspace (Legacy).")
        return True, "Registration successful!"

    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        logger.error(f"Legacy registration API call failed: {error_detail}")
        return False, f"API call failed: {error_detail}"
    except Exception as e:
        logger.error(f"Unexpected error during legacy registration: {e}\n{traceback.format_exc()}")
        return False, f"Unexpected error: {e}"

def get_legacy_assistant_agent_configs_sync(
    as_project_id: str, as_project_number: str,
    agentspace_app: Dict[str, Any], access_token: str,
    assistant_name: str = "default_assistant"
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetches agentConfigs from a legacy Agentspace assistant."""
    logger.info(f"Fetching legacy agent configs: AS Project: {as_project_id}, App: {agentspace_app['engine_id']}, Assistant: {assistant_name}")
    location = agentspace_app['location']
    app_id = agentspace_app['engine_id']
    hostname = f"{location}-discoveryengine.googleapis.com" if location != "global" else "discoveryengine.googleapis.com"
    assistant_api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_name}"

    try:
        headers = {"Authorization": f"Bearer {access_token}", "x-goog-user-project": as_project_id}
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.debug(f"LEGACY_FETCH_CONFIGS_REQUEST:\nURL: {assistant_api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}")
        response = requests.get(assistant_api_endpoint, headers=headers)
        response.raise_for_status()
        agent_configs = response.json().get("agentConfigs", [])
        logger.info(f"Found {len(agent_configs)} legacy agent configs.")
        return agent_configs, None
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        if e.response is not None and e.response.status_code == 404:
            return [], f"Assistant '{assistant_name}' not found." # Return empty list and specific message
        logger.error(f"API Error fetching legacy assistant config: {error_detail}")
        return [], f"API Error: {error_detail}"
    except Exception as e:
        logger.error(f"Unexpected error fetching legacy assistant config: {e}\n{traceback.format_exc()}")
        return [], f"Unexpected error: {e}"

def deregister_agents_sync(
    as_project_id: str, as_project_number: str,
    agentspace_app: Dict[str, Any],
    agent_ids_to_remove: List[str], current_configs: List[Dict[str, Any]],
    assistant_name: str = "default_assistant"
) -> Tuple[bool, str]:
    """Synchronous function to deregister agents by patching the assistant (Legacy API)."""
    logger.info(f"Legacy Deregister: IDs: {agent_ids_to_remove}, AS Project: {as_project_id}, App: {agentspace_app['engine_id']}")
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
            "x-goog-user-project": as_project_id,
        }
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.debug(f"LEGACY_DEREGISTER_REQUEST:\nURL: {patch_endpoint_with_mask}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(payload, indent=2)}")
        response = requests.patch(patch_endpoint_with_mask, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        logger.info(f"Successfully updated Agentspace assistant (Legacy Deregistration). Removed {len(agent_ids_to_remove)} agent(s).")
        return True, f"Successfully deregistered {len(agent_ids_to_remove)} agent(s)."

    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        logger.error(f"API Error during legacy deregistration: {error_detail}")
        return False, f"API Error: {error_detail}"
    except Exception as e:
        logger.error(f"Unexpected error during legacy deregistration: {e}\n{traceback.format_exc()}")
        return False, f"Unexpected error: {e}"

# --- V2 Agentspace API Helpers ---

def register_agent_sync(
    as_project_id: str, as_project_number: str,
    agentspace_app: Dict[str, Any],
    agent_engine_resource_name: str, display_name: str, description: str,
    tool_description: str, icon_uri: str, authorizations_list: Optional[List[str]]
) -> Tuple[bool, str]:
    """Synchronous function to register Agent Engine with Agentspace App using the V2 POST API."""
    logger.info(f"Register Agent: AS Project: {as_project_id} (Num: {as_project_number}), App: {agentspace_app['engine_id']}, AE: {agent_engine_resource_name}, Auths: {authorizations_list}")
    agentspace_app_id = agentspace_app['engine_id']
    agentspace_location = agentspace_app['location']

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh token from ADC for registration.")
            raise ValueError("Failed to refresh token from ADC.")
        access_token = credentials.token

        hostname = f"{agentspace_location}-discoveryengine.googleapis.com" if agentspace_location != "global" else "discoveryengine.googleapis.com"
        api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{agentspace_location}/collections/default_collection/engines/{agentspace_app_id}/assistants/default_assistant/agents"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": as_project_id,
        }
        payload = {
            "displayName": display_name,
            "description": description,
            "icon": {"uri": icon_uri if icon_uri else "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/smart_toy/default/24px.svg"},
            "adk_agent_definition": {
                "tool_settings": {"tool_description": tool_description},
                "provisioned_reasoning_engine": {"reasoning_engine": agent_engine_resource_name}
            }
        }
        if authorizations_list:
            payload["adk_agent_definition"]["authorizations"] = authorizations_list

        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.debug(f"REGISTER_AGENT_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}\nPayload: {json.dumps(payload, indent=2)}")
        response = requests.post(api_endpoint, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"Successfully created agent resource. Name: {response_data.get('name', 'N/A')}")
        return True, f"Successfully created agent resource.\nName: {response_data.get('name', 'N/A')}\nResponse: {json.dumps(response_data, indent=2)}"

    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        logger.error(f"Registration API call failed: {error_detail}")
        return False, f"API call failed: {error_detail}"
    except Exception as e:
        logger.error(f"Unexpected error during registration: {e}\n{traceback.format_exc()}")
        return False, f"Unexpected error: {e}"

def get_all_agents_from_assistant_sync(
    as_project_id: str, as_project_number: str,
    agentspace_app: Dict[str, Any], assistant_name: str = "default_assistant"
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Synchronously fetches all agents (ADK and non-ADK) from a given assistant (V2 API)."""
    logger.info(f"Get All Agents from Assistant: '{assistant_name}', AS Project: {as_project_id}, App: {agentspace_app.get('engine_id')}")
    location = agentspace_app['location']
    app_id = agentspace_app['engine_id']
    hostname = f"{location}-discoveryengine.googleapis.com" if location != "global" else "discoveryengine.googleapis.com"
    api_endpoint = f"https://{hostname}/v1alpha/projects/{as_project_number}/locations/{location}/collections/default_collection/engines/{app_id}/assistants/{assistant_name}/agents"

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh ADC token for agent list.")
            raise ValueError("Failed to refresh ADC token.")
        headers = {"Authorization": f"Bearer {credentials.token}", "X-Goog-User-Project": as_project_id}
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.debug(f"GET_ALL_AGENTS_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}")
        response = requests.get(api_endpoint, headers=headers)
        response.raise_for_status()
        agents_list = response.json().get("agents", [])
        logger.info(f"Found {len(agents_list)} agents.")
        return agents_list, None
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        logger.error(f"API Error fetching agent list: {error_detail}")
        return [], f"API Error: {error_detail}"
    except Exception as e:
        logger.error(f"Unexpected error fetching agent list: {e}\n{traceback.format_exc()}")
        return [], f"Unexpected error: {e}"

def deregister_agent_sync(as_project_id: str, agent_resource_name: str) -> Tuple[bool, str]:
    """Synchronously deregisters a single agent using its full resource name (V2 API)."""
    logger.info(f"Deregister Agent: {agent_resource_name}, AS Project for header: {as_project_id}")
    try:
        parts = agent_resource_name.split('/')
        loc_idx = parts.index('locations') + 1
        agent_location = parts[loc_idx]
    except (ValueError, IndexError):
        logger.error(f"Could not parse location from agent resource name: {agent_resource_name}")
        return False, f"Could not parse location from agent resource name: {agent_resource_name}"

    hostname = f"{agent_location}-discoveryengine.googleapis.com" if agent_location != "global" else "discoveryengine.googleapis.com"
    api_endpoint = f"https://{hostname}/v1alpha/{agent_resource_name}"

    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        if not credentials.token:
            logger.error("Failed to refresh ADC token for deregister.")
            raise ValueError("Failed to refresh ADC token.")
        headers = {"Authorization": f"Bearer {credentials.token}", "X-Goog-User-Project": as_project_id}
        log_headers_masked = {k: ("Bearer [token redacted]" if k == 'Authorization' else v) for k, v in headers.items()}
        logger.debug(f"DEREGISTER_AGENT_REQUEST:\nURL: {api_endpoint}\nHeaders: {json.dumps(log_headers_masked, indent=2)}")
        response = requests.delete(api_endpoint, headers=headers)
        response.raise_for_status()
        logger.info(f"Successfully deregistered agent '{agent_resource_name.split('/')[-1]}'.")
        return True, f"Successfully deregistered agent '{agent_resource_name.split('/')[-1]}'."
    except requests.exceptions.RequestException as e:
        error_detail = f"Status: {e.response.status_code if e.response else 'N/A'}, Body: {e.response.text if e.response else str(e)}"
        logger.error(f"API Error during deregistration: {error_detail}")
        return False, f"API Error: {error_detail}"
    except Exception as e:
        logger.error(f"Unexpected error during deregistration: {e}\n{traceback.format_exc()}")
        return False, f"Unexpected error: {e}"
