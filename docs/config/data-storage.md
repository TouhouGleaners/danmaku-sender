# 用户数据目录与存储结构

程序的所有持久化数据存储在用户数据目录中。目录路径由 `platformdirs` 库根据操作系统自动决定。

---

## 目录位置

=== "Windows"

    ```
    %LOCALAPPDATA%/Miku_oso/BiliDanmakuSender/
    ```

    通常为 `C:\Users\<用户名>\AppData\Local\Miku_oso\BiliDanmakuSender\`

=== "macOS"

    ```
    ~/Library/Application Support/Miku_oso/BiliDanmakuSender/
    ```

=== "Linux"

    ```
    ~/.local/share/Miku_oso/BiliDanmakuSender/
    ```

程序首次运行时会自动创建该目录。

---

## 文件结构

```
BiliDanmakuSender/
├── config.json          # 运行时配置（发送、监视、主题、校验）
├── accounts.json        # 加密的账号凭证（Fernet 加密）
├── history.db           # SQLite 数据库（弹幕发送与核销记录）
└── logs/                # 日志目录
    ├── latest.log          # 应用日志（自动轮转）
    └── ...
```

### config.json

存储所有运行时配置，包括发送节奏、监视参数、主题外观、校验规则等。

- **格式**：JSON
- **编码**：UTF-8
- **写入时机**：控件写回后 800 毫秒自动保存；窗口关闭时兜底保存一次
- **安全性**：不含敏感信息，可直接查看和手动编辑

### accounts.json

存储所有已保存账号的 B 站凭证（SESSDATA、bili_jct）。

- **格式**：JSON（Fernet 加密后的密文）
- **写入时机**：添加/删除/切换账号时
- **安全性**：内容已加密，无法直接读取。解密密钥存储在系统密钥环 (Keyring) 中

### history.db

存储弹幕的发送与核销记录，用于断点续传查重、存活率验证与任务级对账。

- **格式**：SQLite（WAL 模式）
- **ORM**：Peewee
- **存储内容**：弹幕的内容与样式指纹、目标视频、发送与核销状态、时间戳、归属任务；以及任务本身的目标、标题与运行状态
- **查询**：支持按 BV 号、内容、状态搜索

### logs/

存放应用运行日志。日志文件自动轮转，不会无限增长。

---

## 备份与迁移

### 备份

直接复制整个 `BiliDanmakuSender` 目录即可备份所有数据。

### 迁移到新机器

1. 复制整个目录到新机器的对应位置。
2. `config.json` 和 `history.db` 可直接使用。
3. `accounts.json` 需要在新机器上也有对应的 Keyring 密钥才能解密。如果没有，需要重新添加账号。

!!! warning "Keyring 绑定"
    `accounts.json` 的加密密钥存储在本机的系统密钥环中。直接拷贝文件到另一台机器将无法解密，需要重新输入凭证。

!!! note "跨版本"
    `history.db` 会自动升级，旧库可直接使用。旧版 `config.json` 不做迁移，升级后回退为默认值；需要保留的取值在设置页改回。

---

## 磁盘空间

| 文件 | 典型大小 | 增长趋势 |
|:-----|:---------|:---------|
| config.json | < 1 KB | 固定 |
| accounts.json | < 5 KB | 随账号数线性增长 |
| history.db | 数 MB ~ 数十 MB | 随发送记录线性增长 |
| logs/ | 数 MB | 自动轮转，有上限 |
