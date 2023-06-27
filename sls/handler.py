import json
import logging
import os

from notion_client import Client
from slack_sdk import WebClient

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_slack_message_content_and_url(
    message_ts: str, channel_id: str, client: WebClient
):
    res = client.conversations_history(
        channel=channel_id, latest=message_ts, inclusive=True, limit=1
    )
    message = res["messages"][0]["text"]
    ts = res["messages"][0]["ts"]

    if ts != message_ts:
        res = client.conversations_replies(
            channel=channel_id,
            ts=message_ts,
            inclusive=True,
            limit=1,
        )
        message = res["messages"][0]["text"]
        ts = res["messages"][0]["ts"]

    res = client.chat_getPermalink(channel=channel_id, message_ts=ts)
    url = res["permalink"]

    return (message, url)


def reply_to_slack_thread(
    page_url: str, message_ts: str, channel_id: str, client: WebClient
):
    # スタンプの押されたメッセージがリプライの場合、リプライ先を親メッセージにする
    res = client.conversations_replies(
        channel=channel_id, ts=message_ts, limit=1, inclusive=True
    )

    if "thread_ts" in res["messages"]:
        thread_ts = res["messages"][0]["thread_ts"]
        message_ts = thread_ts if message_ts != thread_ts else message_ts

    res = client.chat_postMessage(
        channel=channel_id,
        thread_ts=message_ts,
        text=f"割れ窓タスクに追加しました\n{page_url}",
    )

    return res


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

    slack_bot_user_token = os.getenv(
        "SLACK_BOT_USER_TOKEN", "SLACK_BOT_USER_TOKEN not set"
    )
    slack_reaction = os.getenv("REACTION_NAME", "tada")

    body = json.loads(event["body"])
    logging.info(body)

    # 再送の場合はスキップ
    if "X-Slack-Retry-Num" in event["headers"]:
        logging.info("X-Slack-Retry-Num exists. skipping.")
        return {
            "statusCode": 200,
            "body": "X-Slack-Retry-Num exists. skipping.",
        }

    if "event" in event["body"]:
        stamp = body["event"]["reaction"]
        if stamp != slack_reaction:
            return {
                "statusCode": 200,
                "body": f"Not a {slack_reaction} reaction. skipping",
            }

        channel_id = body["event"]["item"]["channel"]
        message_ts = body["event"]["item"]["ts"]

        bot_client = WebClient(token=slack_bot_user_token)

        message, message_url = get_slack_message_content_and_url(
            message_ts, channel_id, bot_client
        )

        page = notion.databases.query(
            database_id=notion_database_id,
            filter={
                "property": "タスク名",
                "rich_text": {"equals": message},
            },
        )

        if page["results"]:
            logger.info("Page already exists. skipping")
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
        page_url = res["url"]

        res = reply_to_slack_thread(
            page_url, message_ts, channel_id, bot_client
        )
        logging.info(res)

        return {
            "statusCode": 200,
            "body": res,
        }
