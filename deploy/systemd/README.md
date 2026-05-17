# systemd 部署说明 / Deployment Notes

## 中文优先

## 1. 推荐目录

把项目放到类似下面的位置：

```text
/opt/shen-zhiwei-bot
```

并确保目录里有：

- `.env`
- `.venv`
- `src/`
- `requirements.txt`

## 1.1 Dashboard 远程访问说明

默认配置里的 `DASHBOARD_HOST=127.0.0.1` 只会监听服务器本机回环地址。

这意味着：

- 在服务器里执行 `curl http://127.0.0.1:8099` 可能是通的
- 但你在自己电脑浏览器里直接打开 `http://服务器IP:8099` 还是会失败

如果你希望从外部浏览器访问，需要在 `.env` 里显式改成：

```text
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8099
```

注意：当前 Dashboard 没有内建登录鉴权，不建议直接裸露到公网。至少应配合下面任一方案：

- 只在安全组 / 防火墙里放行你自己的 IP
- 放到 Nginx / Caddy 后面并加鉴权
- 通过 SSH 隧道访问，而不是直接开放端口

## 2. 修改 service 模板

模板文件：

[`shen-zhiwei-bot.service`](./shen-zhiwei-bot.service)

需要至少改这几项：

- `User`
- `Group`
- `WorkingDirectory`
- `EnvironmentFile`
- `ExecStart`

## 3. 安装 service

把模板复制到 systemd：

```bash
sudo cp deploy/systemd/shen-zhiwei-bot.service /etc/systemd/system/shen-zhiwei-bot.service
```

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable shen-zhiwei-bot
sudo systemctl start shen-zhiwei-bot
```

## 4. 常用命令

查看状态：

```bash
sudo systemctl status shen-zhiwei-bot
```

查看日志：

```bash
sudo journalctl -u shen-zhiwei-bot -f
```

排查 Dashboard 是否真的在监听：

```bash
sudo ss -lntp | grep 8099
curl http://127.0.0.1:8099
```

如果第二条在服务器本机能打开，但你自己电脑打不开，优先检查：

- `.env` 里的 `DASHBOARD_HOST` 是否还是 `127.0.0.1`
- 云服务器安全组 / 防火墙是否放行了 `8099`
- 是否需要通过反向代理转发到 `8099`

重启：

```bash
sudo systemctl restart shen-zhiwei-bot
```

停止：

```bash
sudo systemctl stop shen-zhiwei-bot
```

---

## English fallback

Place the project under a stable directory such as `/opt/shen-zhiwei-bot`, with `.env`, `.venv`, `src/`, and `requirements.txt` present.

`DASHBOARD_HOST=127.0.0.1` only listens on the server loopback address. To access Dashboard from an external browser, set `DASHBOARD_HOST=0.0.0.0`, then protect the service with firewall rules, Nginx/Caddy auth, or an SSH tunnel.

Update [`shen-zhiwei-bot.service`](./shen-zhiwei-bot.service) for `User`, `Group`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`, then install it with:

```bash
sudo cp deploy/systemd/shen-zhiwei-bot.service /etc/systemd/system/shen-zhiwei-bot.service
sudo systemctl daemon-reload
sudo systemctl enable shen-zhiwei-bot
sudo systemctl start shen-zhiwei-bot
```

Use `systemctl status`, `journalctl -u shen-zhiwei-bot -f`, and `curl http://127.0.0.1:8099` for basic diagnosis.
