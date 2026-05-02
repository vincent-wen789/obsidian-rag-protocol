# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

Obsidianボルトを使って、AIエージェントに「長期記憶」を与える。埋め込みもベクトルDBも不要、すべてローカル。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

---

## 痛み

AIエージェントに「あの件、どう判断したっけ？」と聞いても、毎回ゼロから説明し直し。

メモはちゃんとObsidianに書いてある。エージェントがそれを見られないだけ。

## ORPを入れた後

```
あなた: Coinbase Japan の判断、結局どうだったっけ？

Agent: wiki/career/coinbase-japan-analysis.md
       (last updated 2026-04-11) を参照:
       • status: archived
       • 判断: 規制リスク過大、後発参入劣勢が明確
       • last action: 2026-04-11 分析ノート作成
       Source: alias "Coinbase" がヒット。
```

エージェントは~15KBのJSONインデックスを1つ読み、あなたが定義したエイリアスに対して質問を部分一致で照合し、ヒットしたノート1つだけを読みに行きます。埋め込みなし、外部サービスなし、データは一切マシンの外に出ません。

## 3分でセットアップ

```bash
git clone https://github.com/wjameswen888/obsidian-rag-protocol.git
cd obsidian-rag-protocol
bash hermes/install.sh
```

インストーラーがボルトのパスを尋ね、毎日のcronを設定し、Hermesにindexerを組み込みます。ターミナル1つ、3分で完了。

Hermesを使っていない場合は [その他のエージェント](#その他のエージェント) を参照。system promptルール1つ + cron 1つで接続できます。

## 何をするのか（平たく言うと）

- **ボルトの軽量JSONインデックスを作る**。1ファイル、ノート30件で約15KB。フロントマター（title、aliases、status、last action）を抽出し、高速検索できるよう整えて出力。
- **増分リビルド**。SHA256のコンテンツハッシュで、変更のないノートは再抽出しない。毎日cronで回しても問題なし。
- **エージェントはインデックスだけ読む、ボルトは読まない**。non-trivialな質問に対する最初のtool callは必ず `read_file(vault-index.json)`。エージェントはボルト全体をスキャンしない。
- **エイリアスの部分一致**。キーワードはあなたが管理（フロントマターまたは別JSON）。ヒット → そのノートを読む。ミス → ユーザーに確認。

## 仕組み

```
あなたのボルト                   indexer (cron 毎日)
  ├── wiki/projects/             ┌─────────────────────┐
  ├── wiki/career/         ─────►│ rebuild-vault-      │──┐
  └── hermes-knowledge/          │ index.py            │  │ 出力
                                 │ (SHA256 + frontmatter│  │
                                 └─────────────────────┘  ▼
                                                    vault-index.json
                                                       (~15KB)
                                                          │
                                                          ▼
あなたのエージェント (Hermes / Claude / etc.)
  non-trivialな質問を受け取る
       │
       ├──► read_file(vault-index.json)        # tool call 1回
       ├──► キーワードを aliases と部分一致照合
       ├──► ヒット → read_file(該当ノート)     # tool call 1回
       └──► ミス → ユーザーに確認 / リビルド提案
```

完全な仕様は [OBSIDIAN-RAG-PROTOCOL.md](OBSIDIAN-RAG-PROTOCOL.md) を参照。スキーマ、エイリアス解決、マルチエージェント協調、エラー処理がすべて定義されています。

## ORPが**やらない**こと

- **埋め込みベースではない**。ベクトルもセマンティック検索もなし。質問がエイリアスに当たらない場合、ORPは「それっぽく見つけた」フリをしません。
- **自動タグ付けはしない**。エイリアスはフロントマターか手動マップから来る。indexerが勝手に生成することはなく、検索結果が予測可能。
- **マシン間同期はしない**。ボルトはあなたのPCに。ファイルレイヤーはiCloud / Syncthing / Dropbox等が担当、ORPはその上で動く。
- **ホスト型サービスではない**。Pythonスクリプト1本（標準ライブラリのみ）+ JSONファイル1つ。アカウントもAPI keyも不要。

## あなたに合いますか？

| 状況 | 適合 |
|---|---|
| Obsidianボルトを使っている | ◎ |
| 別のmarkdownノートのフォルダ | ◎ ── ORPは `.md` をスキャンするだけ、「Obsidian」部分はフロントマター慣習を指す |
| ボルトにフロントマターがない | ◎ ファイル名ベースのフォールバックエイリアスで動作。重要ノートに `aliases:` を加えるとさらに精度UP |
| 1000件以上のノート | ◎ ── `--cutoff-days` で作業対象を制限。既にインデックス済みの古いノートは除外されない |
| Hermesユーザー | 直接対応、`install.sh` で完結 |
| Claude Code、Cursor、ChatGPT、自作エージェント | ◎ ── ORPは単なるJSONファイル。[その他のエージェント](#その他のエージェント) 参照 |
| 真のセマンティック検索が欲しい（「Xに関連するノート」） | × ── LlamaIndex / Mem0 等を推奨 |

## その他のエージェント

ORPの本質は「ファイルシステム + JSON」です。任意のエージェントが以下を満たせば使えます:

1. オンデマンドでファイルを読める（`read_file`、`cat`、MCP filesystem server等）
2. system promptルール1行: *"non-trivialな質問では、まず `~/.hermes/vault-index.json` を読み、質問を `aliases` の部分一致で照合し、ヒットしたエントリの `path` を読む。"*

リビルドはcron / launchd / systemd timerなど、プラットフォームに合わせて。エージェント別の接続方法は [INSTALL.md → Agent Integration](INSTALL.md#agent-integration)。

## FAQ

**ノートが外部に送信されることは？**
ありません。indexerはPython標準ライブラリのみ使用、ネットワーク呼び出しはゼロ。インデックスファイルはあなたが指定したパスに置かれます（デフォルト `~/.hermes/vault-index.json`）。

**ノートが800件あるのですが、インデックスは肥大化しますか？**
インデックスのサイズ目標は20KB以下。`--cutoff-days 90`（デフォルト）で過去90日に編集されたノートのみインデックス化。既にインデックスにある古いノートは、ウィンドウから外れただけでは除外されません。

**全ノートにフロントマターを追加する必要がありますか？**
不要です。indexerは先頭段落抽出 + ファイル名ベースのフォールバックで動作。よく参照されるノートに `aliases: [...]` と `summary_points: [...]` を追加すると検索精度が上がります。

**異なるフォルダに同じファイル名のノートがあるとどうなりますか？**
スキャンルート名のプレフィックスで自動的に区別されます（`career-coinbase` vs `projects-coinbase`）。衝突時はstderrに警告。

**インデックスファイルが壊れた場合は？**
`<name>.broken-<ts>` にリネームして保存し、新しいインデックスを再生成。手動で管理していたエイリアスは保存された壊れたファイルから復元可能。

**2つのエージェントで1つのボルトを共有できますか？**
できます ── サンプルの `wiki/` と `hermes-knowledge/` がまさにそれ。各エージェントが自分のディレクトリに書き込み、相手のディレクトリを読みのみで参照。共有 `log.md` のアトミック追記ルールはプロトコル §5.2 に定義。

## 他の選択肢との比較

| アプローチ | ORPとのトレードオフ |
|---|---|
| ボルト全体をsystem promptに貼る | シンプルだが、毎会話でcontextを消費。増分更新なし |
| ベクトルDB / 埋め込み (LlamaIndex / Mem0 / Letta) | セマンティックマッチは効くが重い: チャンキング、埋め込みコスト、検索のブラックボックス化、時間経過によるドリフト |
| Obsidian MCP server | 実時刻でボルトにアクセス可。ただし手動エイリアス層がない ── エージェントが毎回ボルト全体をgrepする必要 |
| **ORP** | エイリアスは明示的（あなたが管理）、検索は決定的、レイテンシほぼゼロ。トレードオフ: エイリアス・キーワード照合のみ、セマンティックマッチなし |

ORPが活きるのは「重要ノートに5つエイリアスを書くほうが、埋め込みのチャンク戦略を調整するよりマシ」と思える人。

## ステータス

仕様はv1.1。reference indexerはPythonファイル1本（~250行、標準ライブラリのみ）。

稼働中:
- 30件のボルトで毎日cronリビルド、3ヶ月稼働
- 2エージェント（Hermes + Claude Code）で1ボルトを共有、書き込みディレクトリは分離

意図的にやっていないこと（現時点）:
- リーダー側のリファレンス実装なし ── サードパーティのエージェントは独自にエイリアス・マッチャーを実装
- セマンティック / ベクトル検索なし
- エイリアスの自動生成なし
- GUI / ダッシュボードなし

## リファレンス

- [`rebuild-vault-index.py`](rebuild-vault-index.py) ── 単一ファイルindexer、標準ライブラリのみ
- [`INSTALL.md`](INSTALL.md) ── インストール、cron / launchd 設定、各エージェント接続方法
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) ── 完全なプロトコル仕様（v1.1）
- [`examples/`](examples/) ── サンプルボルトと生成インデックス

## ライセンス

MIT。[LICENSE](LICENSE) を参照。

[Hermes Agent](https://github.com/nousresearch/hermes-agent) と [Obsidian](https://obsidian.md) の上に構築、ファイルを読めるエージェントなら何でも動作。

メンテナー: [Vincent Wen](https://github.com/wjameswen888)。
