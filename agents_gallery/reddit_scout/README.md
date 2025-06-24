# Reddit Scout Agent

## Overview

The Reddit Scout Agent is designed to fetch the top posts from specified subreddits using the Reddit API. It leverages Google Cloud Secret Manager to securely store and access Reddit API credentials, providing a safe way to handle sensitive information.

> Note: this example was inspired by [Chondashu's](https://github.com/chongdashu) public Github repo: [ADK Made Simple](https://github.com/chongdashu/adk-made-simple). I claim no direct ownership of the original idea.
## Features

- Fetches top "hot" posts from one or more subreddits.
- Retrieves post title, direct link, upvote count, and comment count for each post.
- Securely manages Reddit API credentials using Google Cloud Secret Manager.
- Formats the output as a user-friendly Markdown list.

## Prerequisites

Before you can run or deploy this agent, ensure you have the following:

1.  **Google Cloud Project**:
    *   A Google Cloud Project with billing enabled.
    *   The **Secret Manager API** enabled in your project. You can enable it from the Google Cloud Console.
2.  **Reddit API Credentials**:
    *   You need a Reddit application with a Client ID and Client Secret. You can create one by going to [Reddit Apps](https://www.reddit.com/prefs/apps) and clicking "are you a developer? create an app...". Choose "script" as the app type.
3.  **Python Dependencies**:
    *   `google-adk (>=0.3.0)`
    *   `google-cloud-aiplatform[adk, agent_engines]`
    *   `python-dotenv`
    *   `praw`


## Configuration

This agent requires several configuration steps to function correctly:

1.  **Store Reddit Credentials in Secret Manager**:
    *   In your Google Cloud Project, navigate to the Secret Manager service.
    *   Create two secrets:
        *   One secret to store your Reddit Client ID (e.g., `reddit-client-id`).
        *   Another secret to store your Reddit Client Secret (e.g., `reddit-client-secret`).
    *   **Important**: Note down the exact names (Secret IDs) you give to these secrets.
    *   Ensure the service account or user credentials you'll use to run the agent (either locally or when deployed via Agent Engine) have the **Secret Manager Secret Accessor** IAM role (`roles/secretmanager.secretAccessor`). This permission can be granted on the specific secrets or at the project level.

2.  **Update `constants.py`**:
    Navigate to the agent's constants file located at:
    `reddit_scout/utils/constants.py`

    You **MUST** update the following variables in this file with your specific values:

    *   `sm_project_id`: **Required**. Set this to your Google Cloud Project ID where you stored the Reddit API secrets.
        ```python
        # Example:
        sm_project_id = "your-gcp-project-id"
        ```
    *   `reddit_client_id_secret_key`: **Required**. Set this to the exact name (Secret ID) of the secret you created in Secret Manager for your Reddit Client ID.
        ```python
        # Example:
        reddit_client_id_secret_key = "my-reddit-client-id-secret-name"
        ```
    *   `reddit_client_secret_secret`: **Required**. Set this to the exact name (Secret ID) of the secret you created in Secret Manager for your Reddit Client Secret.
        ```python
        # Example:
        reddit_client_secret_secret = "my-reddit-client-secret-secret-name"
        ```
    *   `reddit_user_agent`: **Required**. Provide a descriptive and unique user agent string for the Reddit API. Reddit requires this, and it helps them identify your script. A good format is `<platform>:<app ID>:<version string> (by /u/<reddit username>)`.
        ```python
        # Example:
        reddit_user_agent = "ADKSampleAgent/1.0 by u/your_reddit_username"
        ```

    **After your updates, `constants.py` might look like this:**
    ```python
    # adk-samples/agents_gallery/reddit_scout/utils/constants.py
    sm_project_id = "my-genai-project-123"
    reddit_client_id_secret_key = "reddit-app-client-id"
    reddit_client_secret_secret = "reddit-app-client-secret"
    reddit_user_agent = "RedditScoutADKSample/1.0 by u/my_reddit_profile"
    ```