# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

Obsidianボルトを使って、AIエージェントに「長期記憶」を与える。**埋め込みもベクトルDBも不要、すべてローカル。** v1.4 から、同じボルトを共有する複数エージェントは「相手の最近の動き」もセッション開始時に共有できる──片方が書けば、もう片方が次のセッションで気づく。

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

## 日々のメンテナンス

ループ全体はこんな感じ:

1. **Obsidianでノートを書く。** フロントマター（`title` / `aliases` / `summary_points`）はあってもなくてもOK ── なくてもファイル名ベースのフォールバックエイリアスで動作する。
2. **インデックスが自動再構築される。** `INSTALL.md` から再構築の起動方法を選ぶ：システムcron / エージェント内蔵スケジューラ / 他のジョブに同梱 / staleになったらエージェントが促す。**よくある組み合わせ**は「日次定時再構築 + staleness-prompt の安全網」。
3. **Recall系の質問でエージェントが自動的にインデックスを読む。** 「Xの件、どう判断したっけ？」→ エージェントが`vault-index.json`を読み、エイリアスにファジーマッチし、該当ノートを読み、コンテキスト付きで回答。
4. **インデックスが古くなったらエージェントが促す。** デフォルト4日以上 → 「再構築しますか？」→ あなたが「再構築」と言う → スクリプトが走る。silent staleなしの設計。
5. **定期的にヘルスチェック。** `python3 orp_health.py` がスキーマ漂移、孤児パス、サイズ超過を検出。CIに組み込むか、ボルト整理後に走らせる。

これだけ。再学習なし、埋め込み再生成なし、ベクトルDB保守なし。

## ORPは読み取り専用ではない

プロトコル面はインデックスだが、実運用ではボルトは双方向に使う ── エージェントは既存ノートを読むだけでなく、トリガー条件下で**ボルトに書き戻す**。本番で使われているパターン例:

| トリガー | 何を書くか | 書き先 |
|---|---|---|
| 日次の求人スキャン cron | その日のマッチした上位N件 | `hermes-knowledge/job-search/daily-push-log.md` |
| 週次マーケットスナップショット | 重要シグナルの一面サマリ | `hermes-knowledge/market/weekly-snapshot-{YYYY-Www}.md` |
| Cron検出した異常（価格 / オンチェーン / マクロ） | 異常イベント記録 | `hermes-knowledge/cron-knowledge/{category}/` |
| エージェントが実質的なタスク完了 | 決定 + 未解決事項 | `wiki/career/` / `wiki/projects/` 等 |
| エージェント間の同期 | 共有ログに追記 | `wiki/log.md`（§5.2 アトミック追記ルールに従う） |

**これらはプロトコル契約の一部ではない**、プロトコルの*応用*だ。エージェントが発火すべきシナリオと書き込み先のディレクトリを設定すれば、第二の脳が自動で蓄積する ── 手でコピペする必要はない。次回再構築でインデックスが新規エントリを取り込む。

## セッション開始時の同期（v1.4+）

v1.3 までの ORP は完全に pull 型だった ── ユーザーが alias にヒットするキーワードを口にしたときだけ、エージェントがインデックスを読みにいく。ここに穴があった。Hermes が深夜 3 時にノートを書いても、その時 Claude Code がオフラインなら、Claude Code は次のセッションでも**まったく気づかない** ── ユーザーがたまたまその件を聞かない限り。

v1.4 はこの穴を塞ぐ。各エージェントはセッション開始時に `orp_reader.py digest --agent <id>` を呼び、共有ログ内で「自分が前回見て以降」追加された内容を受け取る:

```
[ORP digest · agent=cc · since byte 118402 · 2026-05-07T09:15:00+09:00]
🦅[hermes] 2026-05-07T03:14:22+09:00 · write · cron-knowledge/timeout-investigation.md ── 4 つの aux モデル timeout 調査
🦅[hermes] 2026-05-07T08:05:11+09:00 · note · ORP v1.3 alias 一括補完 60 → 58
🦅[hermes] 2026-05-07T08:30:00+09:00 · done · vault-health-check skill 長期化リライト
```

push 側のプロトコル表面はこれで全部だ。実装:

- `wiki/log.md` は従来からの協調チャネル（§5.2）。v1.4 でエントリ形式を固定: ISO-8601 タイムスタンプ + 閉じた action 語彙（`write`/`note`/`done`/`decision`）。これでバイトオフセット cursor が確実にパースできる。
- 各エージェントは自分専用の cursor ファイル `<vault>/.orp/cursor-<id>.json` を持つ ── 他エージェントと干渉しない。
- エージェントがログを書くときは `orp_reader.py log --agent <id> --action <action> "msg"` 経由 ── **`wiki/log.md` を手で編集してはいけない**。手編集すると形式がドリフトし、cursor のパースが壊れる。
- 設計上 best-effort: ボルトが利用不可 / log が存在しない / cursor が破損 → 静かに exit 0。digest の失敗が agent の起動を絶対にブロックしないこと。

mtime スキャンも、デーモンも、ポーリングもなし。append-only な log がただ一つの状態源。各エージェントの接続は hook 一つ。詳細は [INSTALL.md → Session-Start Digest](INSTALL.md#session-start-digest-v14)。

3つ目のエージェント（Codex / Cursor / 自作）を足すには: ID を決める、`orp_reader.py log --agent <id>` で log を書く、セッション開始 hook で `digest --agent <id>` を呼ぶ。ボルト構造を変える必要はない。

## 他の選択肢との比較

| アプローチ | ORPとのトレードオフ |
|---|---|
| ボルト全体をsystem promptに貼る | シンプルだが、毎会話でcontextを消費。増分更新なし |
| ベクトルDB / 埋め込み (LlamaIndex / Mem0 / Letta) | セマンティックマッチは効くが重い: チャンキング、埋め込みコスト、検索のブラックボックス化、時間経過によるドリフト |
| Obsidian MCP server | 実時刻でボルトにアクセス可。ただし手動エイリアス層がない ── エージェントが毎回ボルト全体をgrepする必要 |
| **ORP** | エイリアスは明示的（あなたが管理）、検索は決定的、レイテンシほぼゼロ。トレードオフ: エイリアス・キーワード照合のみ、セマンティックマッチなし |

ORPが活きるのは「重要ノートに5つエイリアスを書くほうが、埋め込みのチャンク戦略を調整するよりマシ」と思える人。

## ステータス

仕様はv1.4。リポジトリには6本の単一ファイルPythonユーティリティ（標準ライブラリのみ、合計約1,800行）。

稼働中:
- 40件ほどのボルト、ノートPC1台で3ヶ月稼働中
- 2エージェント（Hermes + Claude Code）で1ボルトを共有、書き込みディレクトリは分離
- 日次定時再構築 + staleness-prompt の安全網
- セッション開始 digest を両エージェントの startup hook に接続（v1.4）

正直に言うと: これはひとりのユーザーの実運用から育った手作りの仕様だ。**まだ第三者の採用例はない** ── 「コミュニティ標準」ではなく「あなたにも役立つかもしれないもの」として公開している。採用するならissueをあげてほしい、仕様は実使用に合わせて進化させる。

意図的にやっていないこと:
- セマンティック / ベクトル検索なし
- エイリアスの自動生成なし
- GUI / ダッシュボードなし

## リファレンス

- [`rebuild-vault-index.py`](rebuild-vault-index.py) ── 単一ファイルindexer
- [`orp_reader.py`](orp_reader.py) ── 単一ファイルreader（ライブラリ + CLI: `match` / `get` / `status` + v1.4 `log` / `digest`）
- [`orp_health.py`](orp_health.py) ── スキーマ・鮮度・エイリアス被覆率バリデータ
- [`orp_link_check.py`](orp_link_check.py) ── wikilink 整合性スキャナ（fenced code block はスキップ）
- [`expand_aliases.py`](expand_aliases.py) ── frontmatter エイリアスの一括補強（被覆率が薄いとき · spec §3.4）
- [`convert_bare_to_fullpath.py`](convert_bare_to_fullpath.py) ── bare wikilink をフルパスに一括変換（spec §3.5）
- [`INSTALL.md`](INSTALL.md) ── インストール、4種類のトリガー、各エージェント接続方法、session-start digest 配線
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) ── 完全なプロトコル仕様（v1.4）
- [`examples/`](examples/) ── 3件の実ノート、30秒でループ全体を実行可能

## ライセンス

MIT。[LICENSE](LICENSE) を参照。

[Hermes Agent](https://github.com/nousresearch/hermes-agent) と [Obsidian](https://obsidian.md) の上に構築、ファイルを読めるエージェントなら何でも動作。

メンテナー: [Vincent Wen](https://github.com/wjameswen888)。
