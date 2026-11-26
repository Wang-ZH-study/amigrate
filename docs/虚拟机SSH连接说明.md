# 虚拟机 SSH 连接说明

> 写给"忘了怎么连"的自己。照着做能重建整条通道。
> 验证时间：2026-11-25，实测连通。

---

## 一、先澄清方向（最容易记混的地方）

| 方向 | 通不通 | 用途 |
|---|---|---|
| **Windows（这台电脑）→ 虚拟机** | ✅ **通，日常主用** | 在 Windows 上敲 `ssh ic618`，直接在 VM 里跑 Spectre/Calibre |
| 虚拟机 → Windows | ❌ **不通** | Windows 没装 sshd 服务 |

**所以「虚拟机通过 SSH 连接到这个电脑」这个说法反了。**
**实际是「这台电脑通过 SSH 连到虚拟机」** —— 由 Windows 主动发起，VM 当服务器。

如果哪天真的需要反方向（在 VM 里操作 Windows 文件），有两条替代路：
1. **用共享目录**（推荐，见第六节）—— 不用 SSH
2. 装 Windows OpenSSH Server：`Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0`，再 `Start-Service sshd`

---

## 二、网络拓扑

```
┌─────────────────────┐        ┌──────────────┐        ┌────────────────────────┐
│   Windows 宿主机     │        │  VMware NAT   │        │   虚拟机 IC618         │
│                     │        │              │        │   (CentOS 7)           │
│  VMnet8             │        │  vmnet8      │        │   ens33                │
│  192.168.233.1      │◀──────▶│  192.168.233.2│◀──────▶│   192.168.233.128      │
│                     │        │  (网关)       │        │   (DHCP 分配)          │
└─────────────────────┘        └──────────────┘        └────────────────────────┘
        │                                                          │
   用户 IC，密钥认证                                     sshd 监听 22 端口
```

| 项 | 值 |
|---|---|
| Windows VMnet8 适配器 | `192.168.233.1` |
| VMware NAT 网关 | `192.168.233.2` |
| **虚拟机 IP** | **`192.168.233.128`** |
| 虚拟机网络接口 | `ens33`，MAC `00:0c:29:ff:7e:e8` |
| **IP 获取方式** | **DHCP**（`BOOTPROTO="dhcp"`）|
| DHCP 地址池 | `192.168.233.128 ~ 254` |
| 虚拟机用户名 | `IC` |
| SSH 端口 | 22（默认）|

### ⚠️ 关于 IP 是否固定

**DHCP 分配，不保证永久是 .128。**
`.128` 是地址池的第一个，通常先到先得，所以一般不变；但 VM 重启、克隆、改网络后**可能变**。

**IP 变了怎么办**：见第七节排错第 1 条。

### ⚠️ 那个 192.168.122.1 是陷阱

`hostname -I` 会输出两个地址：

```
192.168.233.128   192.168.122.1
      ↑ 这个能用      ↑ 这个连不上
```

`192.168.122.1` 是 **VM 内部 libvirt 网桥**（`virbr0`，给 VM 里再跑容器/虚拟机用的），
**从 Windows 外部不可达**。必须用第一项。

---

## 三、五步重建（从零开始）

### 步骤 1：VMware 网络模式设为 NAT

VMware → 虚拟机设置 → 网络适配器 → **NAT 模式**（对应 VMnet8）

**为什么用 NAT 而不是桥接**：NAT 下 VM 不占用局域网 IP，宿主机能访问、VM 也能上网。
桥接需要路由器分配地址，换网络环境就断。

### 步骤 2：虚拟机装并启动 sshd

```bash
# 在 VM 里（可用 VMware 控制台直接操作）
sudo yum install -y openssh-server      # CentOS 7
sudo systemctl enable sshd
sudo systemctl start sshd
sudo systemctl status sshd              # 应为 active (running)
```

### 步骤 3：Windows 生成密钥对

```powershell
# 在 Windows PowerShell 里
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519_dsh -C "dsh@windows-ic"
# 一路回车（不设 passphrase，为了脚本免交互）
```

生成两个文件：
- `id_ed25519_dsh` —— 私钥（**不要外传**）
- `id_ed25519_dsh.pub` —— 公钥（要放到 VM 上）

**当前公钥内容**（可用来核对）：

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFeLE4l2c/eU0l20uFOels+1WCucWA+ADQVFOKqtVAET dsh@windows-ic
```

### 步骤 4：把公钥写进虚拟机的 authorized_keys

```powershell
# 在 Windows 上执行（把公钥推过去）
$pub = Get-Content "$env:USERPROFILE\.ssh\id_ed25519_dsh.pub"
ssh IC@192.168.233.128 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$pub' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**这一步会提示输一次密码**（此时还没免密）。输完以后就免密了。

**权限要求**（sshd 很挑，权限不对会静默拒绝）：
- `~/.ssh` → `700`
- `~/.ssh/authorized_keys` → `600`

### 步骤 5：写 Windows 的 SSH 配置（给别名）

文件：`C:\Users\Admin\.ssh\config`

```
Host ic618
    HostName 192.168.233.128
    User IC
    IdentityFile ~/.ssh/id_ed25519_dsh
    StrictHostKeyChecking no
    UserKnownHostsFile NUL
    ServerAliveInterval 30
```

**每一项为什么这么写：**

| 配置 | 作用 / 为什么这么设 |
|---|---|
| `Host ic618` | 别名，以后敲 `ssh ic618` 就行 |
| `HostName 192.168.233.128` | VM 的 NAT 地址 |
| `User IC` | VM 里的用户名 |
| `IdentityFile ~/.ssh/id_ed25519_dsh` | 指定用哪把私钥（Windows 上有多个密钥时必需）|
| `StrictHostKeyChecking no` | **VM 重建后 host key 会变**，不关会每次报 `REMOTE HOST IDENTIFICATION HAS CHANGED` |
| `UserKnownHostsFile NUL` | Windows 特例：把 known_hosts 指向空设备，避免不断累积失效条目 |
| `ServerAliveInterval 30` | 每 30 秒发心跳，防止长时间仿真时连接被断开 |

### 验证

```powershell
ssh ic618 "hostname; whoami; hostname -I"
```

期望输出：
```
IC
IC
192.168.233.128 192.168.122.1
```

---

## 四、日常怎么用

```powershell
# 进交互 shell
ssh ic618

# 单条命令（最常用）
ssh ic618 "ls ~/OPA11"

# 跑仿真（长任务放后台）
ssh ic618 "cd ~/somewhere && nohup spectre input.scs > log 2>&1 &"

# 看文件
ssh ic618 "cat ~/CDS.log | tail -20"

# 传文件（小文件）
scp .\local.txt ic618:~/
scp ic618:~/remote.txt .\

# 传整个目录
scp -r .\localdir ic618:~/
```

---

## 五、当前实际配置一览（对照检查用）

### Windows 侧 `~/.ssh/config`

```
Host ic618
    HostName 192.168.233.128
    User IC
    IdentityFile ~/.ssh/id_ed25519_dsh
    StrictHostKeyChecking no
    UserKnownHostsFile NUL
    ServerAliveInterval 30
```

### Windows 侧 `~/.ssh/` 目录

| 文件 | 大小 | 说明 |
|---|---|---|
| `config` | 176 B | 上面的别名配置 |
| `id_ed25519_dsh` | 411 B | 私钥 |
| `id_ed25519_dsh.pub` | 97 B | 公钥 |
| `known_hosts` | 374 B | 主机指纹（我们用 NUL 绕过了它）|

### 虚拟机侧

```bash
~/.ssh/authorized_keys   # 内含上面那把公钥（单行）
sshd                     # active (running)
```

---

## 六、跨机传文件：共享目录（比 scp 方便）

VMware 已经配了共享文件夹，VM 里挂在 `/mnt/hgfs/`：

| VM 内路径 | 对应 Windows 路径 | 说明 |
|---|---|---|
| `/mnt/hgfs/IC-design-first` | `E:\IC-design-first\` | IC 设计项目 |
| `/mnt/hgfs/D` | `D:\` | D 盘整个 |

**注意：`E:\auto-IC-move` 目前不在共享列表里。**

**要把 auto-IC-move 的文件送进 VM，两种办法：**

```powershell
# 办法 A：scp（推荐，不依赖共享配置）
scp -r E:\auto-IC-move\netlists\* ic618:~/autoIC/netlists/

# 办法 B：先拷到共享目录再在 VM 里取
Copy-Item E:\auto-IC-move\netlists\*.scs E:\IC-design-first\exchange\ -Force
ssh ic618 "cp /mnt/hgfs/IC-design-first/exchange/*.scs ~/autoIC/netlists/"
```

**办法 C（一劳永逸）**：VMware 虚拟机设置 → 选项 → 共享文件夹 → 添加 `E:\auto-IC-move`，
然后在 VM 里 `sudo vmhgfs-fuse .host:/ /mnt/hgfs -o allow_other`（或重启）。

---

## 七、排错清单（按出现频率排序）

### 1. `ssh: connect to host ... port 22: Connection timed out`

**最常见原因：VM 的 IP 变了。**

```powershell
# 方法一：VMware 控制台里直接看
# 登录后在 VM 里跑：
hostname -I

# 方法二：从 Windows 扫一遍网段（要先开 VM）
1..254 | ForEach-Object -Parallel {
  $ip = "192.168.233.$_"
  if (Test-Connection $ip -Count 1 -Quiet -TimeoutSeconds 1) { $ip }
} -ThrottleLimit 64

# 找到新 IP 后改 C:\Users\Admin\.ssh\config 里的 HostName
```

### 2. `Permission denied (publickey)`

- 检查 VM 上 `~/.ssh/authorized_keys` 内容是否正确（应该只有一行，就是那把公钥）
- 检查权限：`ls -ld ~/.ssh ~/.ssh/authorized_keys` → 应为 `700` / `600`
- 检查 selinux：`getenforce`，如果是 Enforcing 且刚复制文件，可能需要 `restorecon -R ~/.ssh`

### 3. `REMOTE HOST IDENTIFICATION HAS CHANGED`

**VM 重建后 host key 变了，很正常。**

我们的 config 已经用 `StrictHostKeyChecking no` + `UserKnownHostsFile NUL` 避免了。
如果还报，说明有其他 config 或命令行参数覆盖了，检查 `ssh -v ic618` 看用了哪个 config。

### 4. 长时间仿真时连接断开

`ServerAliveInterval 30` 已经防了。如果还断：

```powershell
ssh ic618 "cd ~/work && nohup spectre input.scs > log 2>&1 &"
```

**用 nohup 让进程脱离 SSH 会话**，断了也不影响仿真。

### 5. 连上了但 `spectre: command not found`

SSH 非交互式 shell 不加载 `.bashrc` 的完整环境。
检查 `~/.bashrc` 里有没有 Spectre 的 PATH，或者用绝对路径：

```bash
ssh ic618 "/opt/eda/cadence/SPECTRE181/bin/spectre -v"
```

### 6. `ssh ic618` 报 `Could not resolve hostname`

config 里的 `HostName` 写成了主机名而不是 IP。
VM 没有固定的 DNS 记录，**必须写 IP**。

---

## 八、重建虚拟机的检查清单

换机器、重建 VM、改网络后，按这个顺序过一遍：

- [ ] VMware 网络适配器 = **NAT**
- [ ] VM 里 `systemctl status sshd` → **active**
- [ ] VM 里 `hostname -I` 拿到 `192.168.233.x`
- [ ] Windows 的 `~/.ssh/config` 里 `HostName` 改成新 IP（如果变了）
- [ ] `ssh ic618 "echo ok"` 能通
- [ ] VM 里 `~/.ssh/authorized_keys` 有公钥、权限 600
- [ ] 共享目录 `/mnt/hgfs/IC-design-first` 能访问

---

## 九、为什么当初只配了单向

**需求决定的**：所有重活在 VM 里（Spectre、Calibre、Virtuoso），
Windows 只负责写脚本、看结果、跑 Python。所以只需要 Windows 能进 VM。

反方向从来没用上，因为：
- 传文件有共享目录，比 SSH 快
- Windows 上的文件本来就存在本地，VM 通过 `/mnt/hgfs` 读就行

**如果以后要在 VM 里调 Windows 的 GUI 程序，再考虑装 sshd，不是现在的需求。**

---

*关联文档：`E:\auto-IC-move\AGENTS.md` §"给 agent 的提示"（仿真环境在虚拟机里）*
*上游项目（IC-design-first）的同类记录：`E:\IC-design-first\AGENTS.md` §三*