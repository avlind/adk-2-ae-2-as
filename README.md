# **Disclaimer**
> **Please be aware that the scripts and tools provided in this repository are offered "as-is" and for experimental/demonstration purposes. You use them at your own risk.**
>
> The Google Cloud Platform (GCP) APIs, particularly those related to Agent Engine and associated services, are subject to rapid changes and updates. While efforts are made to keep these samples current, **the functionality of the included deployment scripts and utilities is only tested and confirmed to work as of Jun 16, 2025.** Beyond this date, compatibility or functionality is not guaranteed without updates. Always refer to the official GCP documentation for the latest API specifications and best practices.

# ADK Samples with Deployment Scripts



>This project uses `uv` for python package management. If you do not have `uv` installed locally, please see the [installation instructions](https://docs.astral.sh/uv/getting-started/installation/). If `uv` is not allowed in your organization or for your own use, I have included a `requirements.txt` file at the project level. You will need to modify any supplied `uv run` commands accordingly.

>Some of the sample agents in this repo were duplicated or inspired from the public [ADK Samples Repo](https://github.com/google/adk-samples) or other previously shared assets. I claim **No CREDIT** for them. All credit is due to the talented engineers that created them. 

## Authors
- Aaron Lind, avlind@

## Prerequisites
- First time in the project you will need to run `uv sync` to build your venv from the uv.lock file.


- Create a .env that contains the required variables. Included is a file named .env.copy that you can use as a template. 
  
    ```bash
    cp .env.copy .env
    ```

- Each ADK Agent may have their own distinct pre-requisites, and setup instructions. Those instructions should be contained in a `README.md` file within the agent's own directory structure. 


## Test Agent Locally with CLI
The simplest way to interact with your agent for local testing is via the Agent Development Kit (ADK) CLI. The standard command is `adk run [your_agent_directory]`, so with `uv` command, if you wanted to test the *search_agent* in this project, the command is listed below.

```bash
uv run adk run ./agents_gallery/search_agent
```

## Test Locally with the Dev UI
The ADK also comes bundled with an Angular UI testing harness for local agent testing. Unlike the CLI, the Angular UI expects to take in a directory that has a directory per agent. The standard command is `adk web [your_directory_of_agents]`. That means to test any of the agents in this repo with the Dev test UI you would execute `adk web agents_gallery` and then navigate to the localhost/port displayed in the terminal for the Dev UI. Then once the UI is up, you'd use the select box in the left panel to choose the agent you want to interact with and test. With `uv` the command is listed below.


```bash
uv run adk web agents_gallery
```

# Agent Setup for Deployment
#### Deployment of ADK Agent to Agent Engine is accomplished via the `webui_manager.py` file. The script will prompt you through any inputs.

- Deployment script **WILL NOT** configure any GCP IAM Permissions for your Agent Engine hosted agent.
- Deployment script assumes that your custom ADK agent is in a dedicated folder in under the `agents_gallery` directory. 
- Before creating an agent, fill in your agent specific dictionary values in the `deployment_utils/deployment_configs.py` file. The parameters follow this syntax:
```json
"your_agent": {
        "module_path": "agents_gallery.your_agent.agent",
        "root_variable": "root_agent",  # root_agent is entrypoint for ADK
        "requirements": [ # Your Agent specific packages, typically anything you would need to pip install
            "google-adk (>=0.3.0)",
            "google-cloud-aiplatform[adk, agent_engines]",
            "dotenv",
        ],
        "extra_packages": [ 
            "./agents_gallery/your_agent",  # Path relative to where interactive_manager.py is run for the agent's directory
        ],
        "local_env_file": "./agents_gallery/tools_agent/.env", #leave empty if not used
        "ae_display_name": "Name for Agent Engine Deployment",
        "as_display_name": "Name when deployed to Agentspace",
        "as_uri": "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/query_stats/default/24px.svg", #icon to be used in Agentspace
        "description": "A description of your agent",
    }
```
# Deployment and Lifecycle Management
>**IMPORTANT**: Deployment scripts run under the context of the GCP Application Default Credentials. If you have not done so already, you must execute `gcloud auth application-default login` to establish the credentials for the deployment scripts.


## Using the Web UI Manager for Agent Lifecycle Management
For a visual approach to managing your ADK agents deployed to Agent Engine, this repo includes a Web UI (developed using the NiceGUI python project) to help with managing the lifecycle of agents.

**General Guidance:**

1.  Ensure you have correctly configured your agent-specific details in the `deployment_utils/deployment_configs.py` file (as outlined in the "Agent Setup for Deployment" section) and any/all `.env` files.
2.  Navigate to the root directory of the project in your terminal.
3.  Launch the UI using the following command, which should launch on port 8080:

    ```bash
    uv run agent_manager.py
    ```
**Tab Descriptions:**

| Tab Name  | Usage |
| ------------- |:-------------:|
| Deploy | Deploys local Agent to Agent Engine based on deployment_config.py |
| Test | Simple Testing UI. Limitation: Only text-in, text-out supported at this time |
| Destroy | Delete an Agent Engine from your GCP Project |
| Manage AuthN | Configure OAuth Authorization for Agentspace, in order to use OAuth with Agent Engine hosted ADK agent. Only needed if ADK agent requires OAuth for its tools/functionality etc. |
| Register | Register an ADK Agent on Agent Engine with an instance of Agentspace in your GCP Project |
| Deregister | Deregister an ADK Agent on Agent Engine from an instance of Agentspace in your GCP Project |


## Known Limitations

- Deployment scripts do not modify any GCP IAM permissions.
- When using the "Test" tab, you cannot manuallly start a new session, you must reload the page to clear the current session and start a new one.
- It is currently not supported to register an ADK on Agent Engine app to an Agentspace in a different project. This experimental feature requires explicit allowlisting by Agentspace engineering team.