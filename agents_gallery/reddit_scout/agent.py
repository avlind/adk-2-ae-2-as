import os

import praw
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.cloud import secretmanager
from praw.exceptions import PRAWException

# Import constants for secret keys
from .utils import constants

load_dotenv(override=True)

def get_secret(
    project_id: str, secret_id: str, version_id: str = "latest"
) -> str | None:
    """Retrieves a secret value from Google Cloud Secret Manager."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(
            f"--- Tool error: Failed to access secret {secret_id} in project"
            f" {project_id}. Error: {e} ---"
        )
        return None


def get_reddit_news(
    subreddit: str,
    limit: int = 5,
) -> dict[str, list[dict[str, str | int]] | list[str]]:
    """
    Fetches top post titles and links from a specified subreddit using the Reddit API.

    Args:
        subreddit: The name of the subreddit to fetch news from (e.g., 'louisville').
        limit: The maximum number of top posts to fetch (default: 5).

    Returns:
        On success: A dictionary with the subreddit name as key and a list of
        dictionaries as value. Each inner dictionary contains 'title' and 'link'
        keys for a post.
        On error: A dictionary with the subreddit name as key and a list containing
        a single error message string as value (e.g., if credentials are missing,
        the subreddit is invalid, or an API error occurs).
    """
    print(
        f"--- Tool called: Fetching from r/{subreddit} via Reddit API (using Secret Manager) ---"
    )

    # Get configuration from constants
    secretmanager_project_id = constants.sm_project_id
    # Use constants imported from utils.constants
    client_id_key = constants.reddit_client_id_secret_key
    # Corrected variable name from constants.py if needed, assuming it's reddit_client_secret_secret_key
    client_secret_key = getattr(constants, 'reddit_client_secret_secret_key', constants.reddit_client_secret_secret)
    user_agent = constants.reddit_user_agent

    # Validate necessary configuration
    if not all([secretmanager_project_id, client_id_key, client_secret_key, user_agent]):
        missing_vars = [
            var
            for var, val in {
                "Secret Manager Project ID": secretmanager_project_id,
                "Reddit Client ID Secret Key": client_id_key,
                "Reddit Client Secret Secret Key": client_secret_key,
                "Reddit User Agent": user_agent,
            }.items()
            if not val
        ]
        print(
            f"--- Tool error: Missing configuration values in constants.py: {', '.join(missing_vars)} ---"
        )
        return {
            subreddit: [
                f"Error: Missing configuration in constants.py ({', '.join(missing_vars)}). Please check agents_gallery/reddit_scout/utils/constants.py."
            ]
        }

    # Retrieve secrets from Secret Manager
    client_id = get_secret(secretmanager_project_id, client_id_key)
    client_secret = get_secret(secretmanager_project_id, client_secret_key)

    if not client_id or not client_secret:
        return {
            subreddit: [
                "Error: Failed to retrieve Reddit API credentials from Secret Manager."
            ]
        }

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            # Adding read_only=True is good practice if you only fetch data
            read_only=True,
        )

        sub = reddit.subreddit(subreddit)
        # Accessing sub.hot will raise appropriate exceptions if invalid/private/banned
        top_posts = list(sub.hot(limit=limit))  # Fetch hot posts

        # Create a list of dictionaries, each containing title, permalink, upvotes and comments.
        # Additional details on the submission attributes can be found here: https://praw.readthedocs.io/en/stable/code_overview/models/submission.html

        posts_data = [
            {
                "title": post.title,
                "link": f"https://www.reddit.com{post.permalink}",
                "upvotes": post.score,
                "comments": post.num_comments,
            }
            
            for post in top_posts
        ]

        if not posts_data:
            return {subreddit: [f"No recent hot posts found in r/{subreddit}."]}

        return {subreddit: posts_data}

    except PRAWException as e:
        # Handle specific PRAW exceptions if needed (e.g., Redirect for non-existent sub)
        print(f"--- Tool error: Reddit API error for r/{subreddit}: {e} ---")
        return {
            subreddit: [
                f"Error accessing r/{subreddit}. It might be private, banned, or non-existent, or there might be an authentication issue. Details: {e}"
            ]
        }
    except Exception as e:  # Catch other potential errors
        print(f"--- Tool error: Unexpected error for r/{subreddit}: {e} ---")
        # Return error in the simpler format
        return {
            subreddit: [
                f"An unexpected error occurred while fetching from r/{subreddit}."
            ]
        }


# Define the Agent
root_agent = Agent(
    name="reddit_scout",
    description="A Reddit Scout that searches for the most relevant posts in a given subreddit, or list of subreddits.",
    model="gemini-2.5-flash",
    instruction=(
        "You are the Reddit News Scout. Your primary task is to fetch and present/top news from Reddit."
        "1. **Identify Intent:** Determine if the user is asking for news or related topics."
        "2. **Determine Subreddit:** Identify which subreddit(s) to check. Use '/r/news' by default if none are specified. Use the specific subreddit(s) if mentioned (e.g., '/r/nyc', '/r/chicago')."
        "3. **Call Tool:** You **MUST** call the `get_reddit_news` tool with the identified subreddit(s). Do NOT generate summaries or links without calling the tool first."
        "4. **Process Tool Output:** The tool will return a dictionary. The key is the subreddit name. The value is either a list of dictionaries (each with 'title', 'link', 'upvotes', and 'comments' keys) on success, or a list containing a single error message string on failure."
        "5. **Format Response:**"
        "   - If the tool returned an error message (a list with one string), report that exact message directly."
        "   - If the tool returned successfully (a list of dictionaries):"
        "     * Start with a sentence indicating the source, like: 'Here are the top posts from r/[subreddit_name]:'"
        "     * Present the posts as a bulleted list."
        "     * For each post, create a Markdown hyperlink where the link text is the post's 'title' and the URL is the post's 'link'. Append the upvote count and comment count. The format for each bullet point MUST be exactly: `* Post Title ⬆️ numberofupvotes 💬numberofcomments`"
        "     * Example: `* Example Post Title ⬆️150 💬30`"
        "   - Do not add any commentary or summaries unless specifically asked."
    ),
    tools=[get_reddit_news],
)
