import os
import json
import base64
import logging
import boto3

from strands import Agent
from strands.telemetry import StrandsTelemetry 
from strands.models.bedrock import BedrockModel
from strands_tools.current_time import current_time
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_api_key
from langfuse import get_client

logger = logging.getLogger("langfuse_agent")
logging.basicConfig(level=logging.INFO)

langfuse_public_key_public_id = os.environ["LANGFUSE_PUBLIC_KEY_SECRET_ID"]
langfuse_public_key_secret_id = os.environ["LANGFUSE_SECRET_KEY_SECRET_ID"]

# Secrets ManagerからLangfuseのキーを取得
# 期待するデータ格納形式:
# - SecretId: "langfuse-public-key" → JSON形式 {"api_key_value":"実際のキー値"}
# - SecretId: "langfuse-secret-key" → JSON形式 {"api_key_value":"実際のキー値"}
secrets_manager = boto3.client("secretsmanager", region_name="us-east-1")

# Langfuse Public Keyを取得（JSON形式 {"api_key_value":"実際のキー値"} から取得）
public_secret = secrets_manager.get_secret_value(SecretId=langfuse_public_key_public_id)
public_data = json.loads(public_secret["SecretString"])
os.environ["LANGFUSE_PUBLIC_KEY"] = public_data["api_key_value"]
print(f"Langfuse パブリックキーを取得: {public_data['api_key_value'][:4]}...{public_data['api_key_value'][-4:]}:")

# Langfuse Secret Keyを取得（JSON形式 {"api_key_value":"実際のキー値"} から取得）
secret_key_secret = secrets_manager.get_secret_value(SecretId=langfuse_public_key_secret_id)
secret_data = json.loads(secret_key_secret["SecretString"])
os.environ["LANGFUSE_SECRET_KEY"] = secret_data["api_key_value"]
print(f"Langfuse シークレットキーを取得: {secret_data['api_key_value'][:4]}...{secret_data['api_key_value'][-4:]}:")

# Tavily APIキーはAgentCore Identityから取得
@requires_api_key(provider_name="tavily-api-key")
def need_tavily_api_key(*, api_key: str):
    print(f"Tavily APIキーを取得: {api_key[:4]}...{api_key[-4:]}")
    os.environ["TAVILY_API_KEY"] = api_key

LANGFUSE_AUTH = base64.b64encode(
    f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
).decode()

os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
    os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com") + "/api/public/otel"
)

os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {LANGFUSE_AUTH}"

# os.environ["LANGFUSE_DEBUG"] = "True"

os.environ["OTEL_TRACES_EXPORTER"] = "otlp"

os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"

strands_telemetry = StrandsTelemetry().setup_otlp_exporter()
langfuse = get_client()

# エージェントのシステムプロンプト
system_prompt = """
あなたは優秀な情報検索エージェントです。
2つのツールを使ってユーザーからの質問を検索・調査し、その内容を簡潔にまとめてください。
回答する際は必ず調査結果をベースとしてください。あなた自身の知識を元に回答することは禁止です。
"""
 
# エージェントのモデル
model = BedrockModel(
    model_id="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
)

app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke_agent(payload: dict):
    user_message = payload.get("prompt", "今日から数えて、今年のre:Inventって何日後？")
    
    # ワークロードアクセストークン用の設定
    os.environ.setdefault("WORKLOAD_NAME", "langfuse-agent")
    os.environ.setdefault("USER_ID", "langfuse")

    # AgentCore IdentityからTavily APIキーを取得
    if not os.environ.get("TAVILY_API_KEY"):
        need_tavily_api_key(api_key="")

    # エージェントをビルドし、実行
    logger.info("[invoke] received prompt (len=%d)", len(user_message))
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY が未取得です。")

    # MCPクライアントの設定
    streamable_http_mcp_client = MCPClient(lambda: streamablehttp_client(f"https://mcp.tavily.com/mcp/?tavilyApiKey={tavily_api_key}"))

    # MCPセッション開始
    with streamable_http_mcp_client:
        # MCPツールを取得後、current_timeツールを追加してエージェントに渡す
        mcp_tools = streamable_http_mcp_client.list_tools_sync()
        agent_tools = mcp_tools + [current_time]

        # エージェントの設定
        agent = Agent(
            model=model,
            tools=agent_tools,
            system_prompt=system_prompt,
            callback_handler=None,
        )
        output = agent(user_message)

        langfuse.flush()

        logger.info("[invoke] done")
        return {"output": output}

if __name__ == "__main__":
    app.run()
