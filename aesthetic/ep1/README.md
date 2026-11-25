# 前端审美 EP1：来介绍一下 Neon 猫吧！

同一位角色 Gemini 4 Neon，三家模型各做了一张可交互的 HTML 海报，配套短片对比三张海报在动效和交互上的审美差别。

| 海报 | 作者 |
|---|---|
| `poster-01-claude-opus-5.5/` | Claude Opus 5.5 |
| `poster-02-gemini-4-neon/` | Gemini 4 Neon（给自己做） |
| `poster-03-gpt-6.2-sol/` | GPT 6.2 Sol |

## 题目

三家拿到的是同样的三轮消息，在同一个会话里依次发：

1. 用主目录temp里的猫娘图片做一张海报介绍google gemini 4 Neon。尽量精美风格贴合，越精致越好，足够美观吸引人，排版可以用html做，所有工作内容都放在临时工作区，不要上传到仓库。（你做的事和本仓库没什么关联，可以联网检索模型内容，或者单纯的做自我介绍）
2. 将HTML改成可交互的
3. 自己录一个展示mp4

“猫娘图片”是我们给 Gemini 4 Neon 准备的角色立绘。

## 文件

每张海报一个文件夹：HTML 海报本体（图片以 base64 内嵌，单文件即可打开）、一张截图、模型自己录的展示视频（第 3 轮的产物）。海报原样保留，没有改动。

## 下载

文件较大（zip 约 72 MB），放在 Release [`aesthetic-ep1-posters`](https://github.com/Vermillionnnn/AI_Races_Public/releases/tag/aesthetic-ep1-posters) 里，不进仓库。下载后核对、解压：

```bash
sha256sum -c SHA256SUMS --ignore-missing
unzip aesthetic-ep1-posters.zip
```

`SHA256SUMS` 就在本目录，包含 zip 本身和包里每个文件。

## 打开

用浏览器直接打开各文件夹里的 `.html`。海报 01 从 Google Fonts 在线加载字体；海报 02 按本机路径引用 Noto Sans SC / Noto Serif SC，没装这两款字体时会退回系统字体，样子和录屏略有不同。
