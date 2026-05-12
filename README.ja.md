# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

**ORP は、複数のAIエージェントが1つの Obsidian ボルトを共有するときに使う、ファイルシステムネイティブな調整プロトコルです。** 各エージェントが他のエージェントの行動を把握するための2つの仕組み：決定論的なノート検索 + append-only な `wiki/log.md` から読む byte-cursor digest──**埋め込みなし、ベクトルDBなし、検索パスに LLM を介在させません**。

> **率直に言うと：** AIエージェント1つで、ボルトを「キュレーション」「書き換え」「最適化」してほしい場合、**これは違うツールです**。[Karpathy の LLM Wiki パターン](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) または [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) を使ってください。ORP が価値を出すのは、複数エージェントが同じボルトに書き込んでいて、それらの間の「サイレントドリフト」が実コストになる場面です。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

### 主要な差別化ポイント

- **Coordination であって curation ではない。** ORP はノートを書き換えない、ボルトを「最適化」しない。コンテンツはあなたのもの、ORP はエージェント間の状態だけを調整する
- **エージェント間の認識共有。** セッション開始時に byte-cursor digest を自動注入──Agent B に Agent A が前回以降に何を書いたかを伝える。ポーリングなし、デーモンなし
- **検索時の LLM オーバーヘッドゼロ。** 決定論的な alias 部分一致のみ、埋め込みも LLM の re-ranking もなし。30 ノートのインデックスは約 15 KB

---

## 痛み

2つの AI エージェントが同じ Obsidian ボルトで作業している。昨晩 Hermes が `hermes-knowledge/` にマーケット分析を書いた。今朝 Claude Code はそれを全く知らない──あなたが説明し直すまでは。毎セッションこの繰り返し。

**左手が右手の動きを知らない。ORP はその間にある共有黒板です。**

（エージェントが1つだけなら、これはあなたの問題ではありません──必要なのは second-brain ツールであって調整プロトコルではありません。冒頭の「率直に言うと」を参照。）

## ORPを入れた後

今朝、新しい Claude Code セッションを開きます。あなたが何も入力する前に、これが自動でエージェントの context に注入されます：

```
[ORP digest · agent=cc · since byte 184459 · 2026-05-12T09:13:15+09:00]
🦅[hermes] 2026-05-12T07:30 · note · stock-pulse 調査完了・アーカイブ済み
🦅[hermes] 2026-05-12T07:31 · write · wukong 文学向け精読レポート — 8/8 endings 全カバー
🦅[hermes] 2026-05-12T08:46 · write · Oppenheimer 文学精読 v1.3.0 — 7/7 endings
```

あなたが一言も発する前に、Claude Code は Hermes が昨晩何をしたかを把握しています。説明し直す必要なし、セッションが共有 context から始まる。

会話の途中で「あの件、どう判断したっけ？」と聞けば、ORP の pull side が動きます：エージェントはあなたが管理する alias にキーワードを部分一致で照合し、ヒットしたノートだけを読みます。約 15 KB の JSON インデックス。埋め込みなし。データはマシンの外に出ません。

## ORP と Karpathy の LLM Wiki / obsidian-second-brain の関係

[Karpathy の LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) や [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) Claude Code skill をすでに知っている方向けです。3つとも同じ近所に住んでいる──markdown ボルト、Obsidian、AIエージェント──しかし解いている問題は違います。**ORP はこれらの代替ではない**、むしろ下に敷いて一緒に使える。

### 一言で

- **Karpathy の LLM Wiki** は*パターン*：LLM が ingest 段階でソースを読み、相互リンクされた markdown ページの wiki を構築・**維持**する。知識は「一度コンパイルして最新を保つ」。**単一エージェント + 人間の協業**設計。
- **obsidian-second-brain** はそのパターンの*実装 + 拡張*：31 のコマンド、4 つの定時 background agent、新しいソースが入ると古いページを**自動で書き換える**、矛盾を自動 reconcile。**単一 Claude Code セッション + 人間**。
- **ORP** は*プロトコル*──同じボルトを共有する複数の AI エージェントが context を共有する：決定論的な alias 部分一致による検索（埋め込みなし）、byte-cursor session-start digest によるエージェント間認識、append-only log による調整。**ボルトの内容はあなたのもの、ORP は書き換えない**。

### スタック上の位置

```
┌──────────────────────────────────────────────┐
│ Application 層 — 知識合成                    │
│ Karpathy の LLM Wiki · obsidian-second-brain│
│ (ingest source / ページ書き換え / lint / save)│
├──────────────────────────────────────────────┤
│ Coordination 層 — 複数エージェント状態同期   │
│ ORP                                          │
│ (digest / log / cursor / alias 部分一致)     │
├──────────────────────────────────────────────┤
│ Storage 層 — markdown + git                  │
│ (Obsidian ボルト / frontmatter / wikilinks)  │
└──────────────────────────────────────────────┘
```

ORP は application 層の下にいます。原理的には obsidian-second-brain は ORP の上で動かせる（各定時 agent が `--agent <id>` で自分を識別、`orp_reader.py log` で log を書く）。Karpathy のパターンは単一エージェントなので調整は不要──ですが、もし Karpathy 風 wiki に2つ目のエージェントを足した瞬間、ORP の調整層が活躍します。

### サイドバイサイド

| 軸 | Karpathy の LLM Wiki | obsidian-second-brain | **ORP** |
|------|---------------------|----------------------|---------|
| **解決する問題** | 知識を蓄積（RAG の毎回再導出を回避） | ボルトの自己維持 | 同じボルトで複数エージェントの状態同期 |
| **層** | Application（知識） | Application（知識） | Coordination（状態） |
| **エージェント数** | 1 + 人間 | 1 + 人間（CC） | 2（CC + Hermes）、拡張可能 |
| **ボルトのページを書き換える？** | はい（ingest 時に LLM が書き換え） | はい、積極的に（書き換え + 矛盾 reconcile）| **いいえ**（append-only log、ボルト内容は不変）|
| **検索方式** | クエリ時に LLM 実行 | クエリ時 LLM + キャッシュページ | **決定論的な部分一致 alias、LLM・埋め込みなし** |
| **埋め込み / ベクトル DB** | 明示なし | オプション（Perplexity sonar による調査） | **完全に不使用 — by design** |
| **awareness 原語** | wiki / ページグラフ全体を読む | `## For future Claude` プリアンブルを自動ロード | エージェントごとの byte-offset cursor で `log.md` を読む |
| **実装規模** | 1500 ワードの gist（idea ファイル） | 31 コマンド、4 cron agent、hook システム | 6 stdlib Python ファイル（約 1900 行） |
| **複数エージェントネイティブ** | いいえ | いいえ | **はい** |

### いつどれを使うか

- **AI 1つに、読書ノートが時とともに蓄積していく wiki を維持してほしい** → Karpathy のパターン（既製がよければ obsidian-second-brain）
- **AI 1つに、second brain 全体を管理してほしい**（kanban、daily notes、矛盾 reconcile、定時 agent） → obsidian-second-brain
- **2つ以上の AI エージェントが同じボルトに書いていて、互いに何をしたか把握する必要がある** → ORP（知識合成も同時に欲しければ、上記2つと組み合わせて使える）

### ORP がやろうとしていないこと

- **wiki 維持ツールではない。** ORP はソースを要約しない、entity ページを更新しない、矛盾を reconcile しない。エージェント同士の調整層であって、ボルトに何を書くかはエージェント次第
- **知識蓄積器ではない。** LLM 駆動のページ書き換えはない。**ORP の append-only log は「ボルト自己書き換え」の逆方向の設計判断**──コンパクトさのために audit trail を失う交換は、私たちはしない
- **Claude Code skill ではない。** ORP は任意のエージェントが実装できるファイルシステムプロトコル（CC と Hermes はリファレンス実装）；上に乗る skill パッケージは application 層の仕事

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

**v1.5 更新：PostToolUse + Stop hook による自動 log。** v1.4 の dogfood データから、chat 型エージェント（Claude Code など）は vault 書き込み後の `orp_reader.py log` 呼び出しを頻繁に忘れることが判明しました（1週間で約 41 件の vault 書き込みに対し、CC の log 件数は 0；同期間に Hermes は 47 件）。プロンプトレベルの MUST は経験的に機能しません。v1.5 ではオプションの2 hook 機構を提供：PostToolUse stager が各 vault 編集をセッションごとの pending ファイルに記録し、Stop hook flusher がターン終了時に1件のサマリ log を書きます（action は `note`、message プレフィックスは `auto:`）。**1ターン1件**、編集ごと1件ではなく──シグナル密度を保つため。Hermes 系の長寿命バックグラウンドエージェントはすでに信頼できる log を書けているので、この機構は不要です。詳しくは [INSTALL.md → Auto-log Hooks](INSTALL.md#auto-log-hooks-v15) と spec §5.6 を参照。

## 他の選択肢との比較

| アプローチ | ORPとのトレードオフ |
|---|---|
| ボルト全体をsystem promptに貼る | シンプルだが、毎会話でcontextを消費。増分更新なし |
| ベクトルDB / 埋め込み (LlamaIndex / Mem0 / Letta) | セマンティックマッチは効くが重い: チャンキング、埋め込みコスト、検索のブラックボックス化、時間経過によるドリフト |
| Obsidian MCP server | 実時刻でボルトにアクセス可。ただし手動エイリアス層がない ── エージェントが毎回ボルト全体をgrepする必要 |
| **ORP** | エイリアスは明示的（あなたが管理）、検索は決定的、レイテンシほぼゼロ。トレードオフ: エイリアス・キーワード照合のみ、セマンティックマッチなし |

ORPが活きるのは「重要ノートに5つエイリアスを書くほうが、埋め込みのチャンク戦略を調整するよりマシ」と思える人。

## ステータス

仕様はv1.5。リポジトリには6本の単一ファイルPythonユーティリティ（標準ライブラリのみ、約1,900行）+ 2つのリファレンス hook スクリプト。

稼働中:
- 40件ほどのボルト、ノートPC1台で3ヶ月稼働中
- 2エージェント（Hermes + Claude Code）で1ボルトを共有、書き込みディレクトリは分離
- 日次定時再構築 + staleness-prompt の安全網
- セッション開始 digest を両エージェントの startup hook に接続（v1.4）
- Claude Code 側に PostToolUse + Stop 自動 log hook（v1.5）── v1.4 dogfood で見えた「CC が vault に書いても log しない」ギャップを補完

正直に言うと: これはひとりのユーザーの実運用から育った手作りの仕様だ。**まだ第三者の採用例はない** ── 「コミュニティ標準」ではなく「あなたにも役立つかもしれないもの」として公開している。採用するならissueをあげてほしい、仕様は実使用に合わせて進化させる。

意図的にやっていないこと:
- セマンティック / ベクトル検索なし
- エイリアスの自動生成なし
- GUI / ダッシュボードなし
- wiki の自己書き換えなし（上記比較セクション参照──append-only log は「ボルト自己書き換え」とは逆方向の設計判断）

## リファレンス

- [`rebuild-vault-index.py`](rebuild-vault-index.py) ── 単一ファイルindexer
- [`orp_reader.py`](orp_reader.py) ── 単一ファイルreader（ライブラリ + CLI: `match` / `get` / `status` + v1.4 `log` / `digest`）
- [`orp_health.py`](orp_health.py) ── スキーマ・鮮度・エイリアス被覆率バリデータ
- [`orp_link_check.py`](orp_link_check.py) ── wikilink 整合性スキャナ（fenced code block はスキップ）
- [`expand_aliases.py`](expand_aliases.py) ── frontmatter エイリアスの一括補強（被覆率が薄いとき · spec §3.4）
- [`convert_bare_to_fullpath.py`](convert_bare_to_fullpath.py) ── bare wikilink をフルパスに一括変換（spec §3.5）
- [`examples/orp-vault-stage.py`](examples/orp-vault-stage.py) + [`orp-vault-flush.py`](examples/orp-vault-flush.py) ── v1.5 PostToolUse + Stop hook リファレンス実装（spec §5.6）
- [`INSTALL.md`](INSTALL.md) ── インストール、4種類のトリガー、各エージェント接続方法、session-start digest 配線、auto-log hook 配線
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) ── 完全なプロトコル仕様（v1.5）
- [`examples/`](examples/) ── 3件の実ノート + v1.5 hook スクリプト

## ライセンス

MIT。[LICENSE](LICENSE) を参照。

[Hermes Agent](https://github.com/nousresearch/hermes-agent) と [Obsidian](https://obsidian.md) の上に構築、ファイルを読めるエージェントなら何でも動作。

メンテナー: [Vincent Wen](https://github.com/wjameswen888)。
