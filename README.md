# strands-agent-with-langfuse-on-agentcore

Strands Agents SDKで構築したエージェントをBedrock AgentCoreへデプロイし、Langfuseでトレースが取得できるようにしてみました。
以下のリポジトリを参考にして、LangfuseのキーをSecrets Managerで保管する想定で少しアレンジしています。

https://github.com/moritalous/strands-agents-langfuse

## コマンド

前提として、Secrets Managerに `langfuse-public-key` と `langfuse-secret-key` の2つのシークレットを設定してください。
格納形式は以下のjson形式です。

```json
{"api_key_value": "<langfuse-key>"}
```

以下をターミナルで実行します。

```bash
$ agentcore launch \
  --env LANGFUSE_PUBLIC_KEY_SECRET_ID=langfuse-public-key \
  --env LANGFUSE_SECRET_KEY_SECRET_ID=langfuse-secret-key \
  --env DISABLE_ADOT_OBSERVABILITY=true \
  --env LANGFUSE_HOST=https://us.cloud.langfuse.com
```

以下をターミナルで実行後、Langfuseのコンソールを確認します。

```bash
$ agentcore invoke '{"prompt": "今日の日付は？"}' --user-id "langfuse"
```

## エラー対処

参考にしたリポジトリのコードをそのまま使うと、私の環境では以下のエラーが出ました。

```text
WARNING:opentelemetry.exporter.otlp.proto.grpc.exporter:Transient error StatusCode.UNAVAILABLE encountered while exporting traces to localhost:4317, retrying in 1s.
```

この警告は別のOTLPパイプライン(gRPC)が localhost:4317 に送ろうとして失敗しているのが原因です。
AgentCoreはデフォルトだと `opentelemetry-instrument` という形でテレメトリーを初期化するのですが、これがgRPCとなっております。

ただ、[LangfuseはgRPCに対応しておらず、代わりにHTTP/protobutを用いる必要がある](https://langfuse.com/integrations/native/opentelemetry)ようです。
なので環境変数に設定すると同時に、`opentelemetry-instrument` での初期化をしないようにDockerfileを修正しています。
