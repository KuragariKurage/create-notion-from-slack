import json
import logging
import os

from notion_client import Client
from slack_sdk import WebClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_slack_message_content_and_url(
    message_ts: str, channel_id: str, slack_user_token: str
):
    client = WebClient(token=slack_user_token)

    res = client.conversations_history(
        channel=channel_id, latest=message_ts, inclusive=True, limit=1
    )
    message = res["messages"][0]["text"]

    res = client.chat_getPermalink(channel=channel_id, message_ts=message_ts)
    url = res["permalink"]

    return (message, url)


def main(event: dict, context: dict):
    if "challenge" in event["body"]:
        body = json.loads(event["body"])
        logging.info(body)
        return {
            "statusCode": 200,
            "body": body["challenge"],
        }

    notion_api_secret = os.getenv(
        "NOTION_API_TOKEN", "NOTION_API_TOKEN not set"
    )
    notion_database_id = os.getenv(
        "NOTION_DATABASE_ID", "NOTION_DATABASE_ID not set"
    )
    notion = Client(auth=notion_api_secret)

    slack_user_token = os.getenv(
        "SLACK_USER_TOKEN", "SLACK_USER_TOKEN not set"
    )
    slack_reaction = os.getenv("REACTION_NAME", "tada")

    body = json.loads(event["body"])
    logging.info(body)

    if "event" in event["body"]:
        stamp = body["event"]["reaction"]
        if stamp != slack_reaction:
            return {
                "statusCode": 200,
                "body": f"Not a {slack_reaction} reaction. skipping",
            }

        channel_id = body["event"]["item"]["channel"]
        message_ts = body["event"]["item"]["ts"]
        message, message_url = get_slack_message_content_and_url(
            message_ts, channel_id, slack_user_token
        )

        page = notion.databases.query(
            database_id=notion_database_id,
            filter={
                "property": "タスク名",
                "rich_text": {"equals": message},
            },
        )

        if page["results"]:
            return {
                "statusCode": 200,
                "body": "Page already exists. skipping",
            }

        page_object = {
            "parent": {
                "database_id": notion_database_id,
            },
            "icon": {"type": "emoji", "emoji": "🐞"},
            "properties": {
                "タスク名": {
                    "title": [{"text": {"content": message}}],
                },
                "タグ": {
                    "multi_select": [
                        {
                            "name": "割れ窓",
                        }
                    ]
                },
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": "slack link",
                                    "link": {"url": message_url},
                                }
                            }
                        ]
                    },
                }
            ],
        }

        res = notion.pages.create(**page_object)

        return {"status": 200, "body": res}
