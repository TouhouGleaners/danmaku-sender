# 弹幕发射工具
一个基于Python的弹幕发射工具，可批量将xml格式弹幕文件中的弹幕发射到指定视频

## 功能特性
- 支持大批量的弹幕发射
- 精确的实时发射日志，动态延迟区间，自动保存账号登录信息
- xml检查功能，检查xml内无法发送的弹幕。视频内弹幕状况监视器

## 快速开始
### 前置条件
- 需要微软雅黑字体

### 安装步骤
1. 进入项目：`https://github.com/TouhouGleaners/danmaku-sender/releases/tag/v1.0.0-alpha`
2. 下载程序：`BiliDanmakuSender-v1.0.0-alpha.exe
3. 在下载路径内找到并启动exe

### 使用教程
1.打开bilibili网页端，按下F12或者右键网页点击检查（不同浏览器可能打开方式不同，以EDGE浏览器为例）
2.切换到应用程序页（顶栏加号左边图标）
3. 在左侧菜单中，找到 "存储"(Storage) -> "Cookies" -> "https://www.bilibili.com"。
4. 复制 SESSDATA 和 BILI_JCT 的 "值"(Value) 列内容，粘贴到本工具对应的输入框。
5.在输入框内输入BV号。获取分P，在下方选择分P
6.选择你的xml文件
7.设置延迟区间（推荐20秒起步，防止因为发送频繁导致发送失败）
8.点击开始任务
校验器使用：
1.选择分P(用以检查弹幕时间戳）
2.选择弹幕文件
3.点击弹幕校验器标签页，点击开始验证。
4.双击单条弹幕，在文本框内修改弹幕内容。或单击单条弹幕删除。
5.应用所有修改（没有这步之前任何修改都不会保存）

## 发射场作者 miku_oso 。 b站https://space.bilibili.com/442719202?spm_id_from=333.1387.follow.user_card.click
