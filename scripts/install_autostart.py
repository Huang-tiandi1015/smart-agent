"""注册「Smart Agent」开机自启计划任务（登录时运行，pythonw 隐藏窗口）。

用法：.venv/Scripts/python scripts/install_autostart.py
卸载：.venv/Scripts/python scripts/uninstall_autostart.py

用临时 XML + schtasks 注册：显式 WorkingDirectory、带空格路径不踩引号坑、
配置 RestartOnFailure（失败 1 分钟后重试 3 次）与 ExecutionTimeLimit=PT0S（不限时）。
全程仅用系统自带 schtasks，无外部依赖，无需管理员权限（LeastPrivilege 登录时任务）。
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "Smart Agent"
PYTHONW = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
RUN_SERVER = PROJECT_ROOT / "scripts" / "run_server.py"

XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Smart Agent 服务：登录时自动后台启动（pythonw 隐藏窗口）</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <UserId>{user}</UserId>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>"{run_server}"</Arguments>
      <WorkingDirectory>{root}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def main() -> int:
    if not PYTHONW.is_file():
        print(f"错误: 未找到 {PYTHONW}\n请先创建 .venv 并安装依赖（requirements.txt）")
        return 1

    xml = XML_TEMPLATE.format(
        user=escape(getpass.getuser()),
        pythonw=escape(str(PYTHONW)),
        run_server=escape(str(RUN_SERVER)),
        root=escape(str(PROJECT_ROOT)),
    )
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
            tmp_path = tmp.name
        with open(tmp_path, "w", encoding="utf-16") as f:
            f.write(xml)
        result = subprocess.run(
            ["schtasks", "/create", "/tn", TASK_NAME, "/xml", tmp_path, "/f"],
            capture_output=True, text=True, errors="replace",
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if result.returncode != 0:
        print("注册失败:")
        print((result.stdout + result.stderr).strip())
        return result.returncode

    print(f"已注册计划任务 '{TASK_NAME}'（登录时自动后台启动服务）")
    print(f'查看状态: schtasks /query /tn "{TASK_NAME}"')
    print(f'立即触发测试: schtasks /run /tn "{TASK_NAME}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
