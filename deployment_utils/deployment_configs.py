# Dictionary mapping agent names (used in --agent_name flag) to their specific configurations.
AGENT_CONFIGS = {
    "tools_agent": {
        "module_path": "agents_gallery.tools_agent.agent",
        "root_variable": "root_agent",  # root_agent is expected entrypoint for ADK
        "requirements": [
            "google-adk==1.9.0",
            "google-cloud-aiplatform[adk, agent_engines]==1.106.0",
            "python-dotenv",
            "google-cloud-secret-manager",
        ],
        "extra_packages": [
            "./agents_gallery/tools_agent",  # Path relative to where interactive_deploy.py is run
        ],
        "local_env_file": "./agents_gallery/tools_agent/.env", #leave empty if not used
        "ae_display_name": "Tools Demo Agent",
        "ae_service_acct": "agentengineuserserviceacct@csaw-workshop1.iam.gserviceaccount.com",  #omit to use default service account
        "as_display_name": "Tools Demo Agent",
        "description": "An agent demonstrating the use of various simple tools.",
        "as_tool_description": "An agent demonstrating the use of various simple tools.", #optional, used by the default assistant of agentspace to know when to call this agent as an agent tool.
    },
    "recipe_finder": {
        "module_path": "agents_gallery.recipe_finder.agent",
        "root_variable": "root_agent",  # root_agent is expected entrypoint for ADK
        "requirements": [
            "google-adk==1.4.2",
            "google-cloud-aiplatform[adk, agent_engines]==1.98.0",
            "python-dotenv",
        ],
        "extra_packages": [
            "./agents_gallery/recipe_finder",  # Path relative to where interactive_deploy.py is run
        ],
        "local_env_file": "./agents_gallery/recipe_finder/.env", #leave empty if not used
        "ae_display_name": "Recipe Finder Demo Agent",
        "ae_service_acct": "",  #omit to use default service account
        "as_display_name": "Recipe Finder in AS",
        "description": "An agent using vertex ai search datastore pointing to gcs bucket full of pdf files containing cooking recipes.",
    },
    "basic_agent": {
        "module_path": "agents_gallery.basic_agent.agent",
        "root_variable": "root_agent",  # root_agent is expected entrypoint for ADK
        "requirements": [
            "google-adk==1.4.2",
            "google-cloud-aiplatform[adk, agent_engines]==1.98.0",
            "python-dotenv",
        ],
        "extra_packages": [
            "./agents_gallery/basic_agent",  # Path relative to where interactive_deploy.py is run
        ],
        "ae_display_name": "Basic Agent",
        "ae_service_acct": "",  #omit to use default service account
        "as_display_name": "Basic Agent",
        "description": "An very basic LLM Agent",
        "as_tool_description": "An very basic LLM Agent",
    },
    "loop_agent": {
        "module_path": "agents_gallery.loop_agent.agent",
        "root_variable": "root_agent",  # root_agent is expected entrypoint for ADK
        "requirements": [
            "google-adk==1.4.2",
            "google-cloud-aiplatform[adk, agent_engines]==1.98.0",
            "python-dotenv",
        ],
        "extra_packages": [
            "./agents_gallery/loop_agent",  # Path relative to where interactive_deploy.py is run
        ],
        "ae_display_name": "Debate Team",
        "ae_service_acct": "",  #omit to use default service account
        "as_display_name": "Debate Team",
        "description": "A Debate Team agent that demonstrates looping functionality within ADK",
        "as_tool_description": "A Debate Team agent that demonstrates looping functionality within ADK",
    },
    "search_agent": {
        "module_path": "agents_gallery.search_agent.agent",
        "root_variable": "root_agent",  # root_agent is expected entrypoint for ADK
        "requirements": [
            "google-adk==1.4.2",
            "google-cloud-aiplatform[adk, agent_engines]==1.98.0",
            "python-dotenv",
        ],
        "extra_packages": [
            "./agents_gallery/search_agent",  # Path relative to where interactive_deploy.py is run
        ],
        "ae_display_name": "Basic Search Agent",
        "ae_service_acct": "",  #omit to use default service account
        "as_display_name": "Basic Search Agent for AS",
        "description": "A Simple LLM Agent empowered with Google Search Tools",
        "as_tool_description": "A Simple LLM Agent empowered with Google Search Tools",
    },
    "reddit_scout_agent": {
        "module_path": "agents_gallery.reddit_scout.agent",
        "root_variable": "root_agent",  # root_agent is expected entrypoint for ADK
        "requirements": [
            "google-adk==1.4.2",
            "google-cloud-aiplatform[adk, agent_engines]==1.98.0",
            "python-dotenv",
            "google-cloud-secret-manager",
            "praw",
        ],
        "extra_packages": [
            "./agents_gallery/reddit_scout",  # Path relative to where interactive_deploy.py is run
        ],
        "ae_display_name": "Reddit Scout",
        "ae_service_acct": "",  #omit to use default service account
        "as_display_name": "Reddit Scout for Agentspace",
        "as_uri": "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/article_person/default/24px.svg",
        "description": "A Reddit scout that searches for the most relevant posts in a given subreddit, or list of subreddits and surfaces them to the user in a conside and consumable manner.",
        "as_tool_description": "A Reddit scout that searches for the most relevant posts in a given subreddit, or list of subreddits and surfaces them to the user in a conside and consumable manner.",
    },
    
}
