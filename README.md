# 板橋ビュータワー UR監視キット

このキットは、**板橋ビュータワー**のURページを定期監視し、結果を**メール通知**するための最小構成です。

## 監視対象
- 物件詳細ページ  
  https://www.ur-net.go.jp/chintai/kanto/tokyo/20_6330.html
- 部屋情報ページ  
  https://www.ur-net.go.jp/chintai/sp/kanto/tokyo/20_6330_room.html
- 板橋駅一覧ページ  
  https://www.ur-net.go.jp/chintai/kanto/tokyo/eki/1573.html
- 新板橋駅一覧ページ  
  https://www.ur-net.go.jp/chintai/kanto/tokyo/eki/2305.html

## 何を通知するか
- URL
- 確認時刻
- 空室推定値（自動判定）
- 前回からページ内容が変わったか
- 判定に使った本文抜粋

## この構成の考え方
UR側の表示はページごとに粒度が違うので、**空室件数だけを1か所で信じるより、複数ページを同時監視し、さらに本文差分も拾う**構成にしています。

つまり、
- 空室数の明示が出たらそれを拾う
- 表示文言が変わっただけでも検知する
- 自動判定が外れても、メール本文のURLと抜粋で人間が再確認できる

この三段構えです。

## 推奨運用
GitHub Actionsで15〜60分おきに動かすのが現実的です。  
同梱のworkflowは、**JST 10:02 / 13:02 / 16:02 / 19:02** に動く設定です。

「石田さんが最初に考えていた10時と13時の2回だけ」にするなら、`.github/workflows/ur-watch.yml` の cron を以下へ変更してください。

```yaml
schedule:
  - cron: '2 1,4 * * *'   # JST 10:02 / 13:02
```

## GitHubでの使い方
1. GitHubで新しいprivate repositoryを作る  
2. このフォルダの中身を全部アップロードする  
3. GitHubの **Settings > Secrets and variables > Actions** で以下を登録する

### 必須Secrets
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `MAIL_FROM`
- `MAIL_TO`
- `NOTIFY_MODE`

### Gmailで送る場合の例
- `SMTP_HOST` = `smtp.gmail.com`
- `SMTP_PORT` = `587`
- `SMTP_USERNAME` = ご自身のGmail
- `SMTP_PASSWORD` = Googleアプリパスワード
- `MAIL_FROM` = ご自身のGmail
- `MAIL_TO` = `ishida1125@gmail.com`
- `NOTIFY_MODE` = `always`

## 通知モード
- `always` : 毎回通知
- `changes_only` : ページ差分があったときだけ通知
- `availability_only` : 空室あり判定が出たときだけ通知（初回は送る）

石田さんの用途なら、まずは **`always`** 推奨です。

このキットでは、受信先は **`ishida1125@gmail.com`** を前提にしてあります。

## ローカル実行
```bash
pip install -r requirements.txt
cp .env.example .env
# .env の値を設定
export $(grep -v '^#' .env | xargs)
python ur_watch.py --state-file .state/ur_state.json
```

## 注意
- UR側のHTML構造が変わると、自動判定ロジックは調整が必要です。
- ただしこの構成は「本文差分」も拾うので、完全に空振りしにくい設計にしています。
- 駅一覧ページには「空室は前日以前の状況」と出ることがあります。よって**ページ更新検知 + 即電話確認**の組み合わせが実務的です。
