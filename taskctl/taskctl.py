#!/usr/bin/env python3

import argparse
from asyncio import all_tasks
from operator import call
import signal
import subprocess
import os
from datetime import datetime
import json
import hashlib
from typing import Optional, Literal
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, asdict
import textwrap


LOG_DIR = Path.home() / ".taskctl"

def get_log_path(cmd_name: str) -> Path:
    return LOG_DIR / f"{cmd_name}.log"

def get_info_path(cmd_name: str) -> Path:
    return LOG_DIR / f"{cmd_name}.info.json"

class Status(Enum):
    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"

@dataclass
class TaskInfo:
    cmd: str
    cmd_name: str
    pid: int
    start_time: str
    duration: Optional[float] = None
    end_time: Optional[str] = None
    status: Literal["running", "done", "stopped"] = Status.RUNNING.value
    exit_code: Optional[int] = None

def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def tail_log(log_file: Path, num_lines=10):
    if not log_file.exists():
        print(f"日志文件不存在: {log_file}")
        return

    print(f"正在查看日志: {log_file}")
    try:
        subprocess.run(["tail", "-n", str(num_lines), "-f", str(log_file)])
    except KeyboardInterrupt:
        print("\n已退出日志查看模式")


def run(cmd_string: str, cmd_name: Optional[str], watch: bool):
    now = datetime.now()
    if cmd_name is None:
        cmd_name = f"{now.strftime("%Y%m%d%H%M%S")}_{hashlib.md5(cmd_string.encode()).hexdigest()}"
    log_file = get_log_path(cmd_name)
    info_file = get_info_path(cmd_name)
    if info_file.exists():
        with info_file.open("r") as f:
            existing_info = TaskInfo(**json.load(f))
            if existing_info.status == Status.RUNNING.value and is_pid_running(existing_info.pid):
                print(f"任务 [{cmd_name}] 已存在且正在运行，无法重复启动")
                return
            else:
                print(f"任务 [{cmd_name}] 已完成，覆盖旧文件")
    info_file.unlink(missing_ok=True)
    log_file.unlink(missing_ok=True)
    print(f"启动任务 [{cmd_name}]: {cmd_string}")
    wrapped_cmd = textwrap.dedent(f"""
        {cmd_string}
        EXIT_CODE=$?
        python3 {__file__} callback "{cmd_name}" $EXIT_CODE
        exit $EXIT_CODE
    """).strip()
    process = subprocess.Popen(
        ["bash", "-c", wrapped_cmd],
        stdout=log_file.open("a"),
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    pid = process.pid
    info = TaskInfo(
        cmd=cmd_string,
        cmd_name=cmd_name,
        pid=pid,
        start_time=now.strftime("%Y-%m-%d %H:%M:%S.%f"),
    )
    info_file.write_text(json.dumps(asdict(info), indent=4))
    if watch:
        print("进入 watch 模式...")
        tail_log(log_file)

def get_running_tasks() -> list[str]:
    cmd_names = []
    for info_file in LOG_DIR.glob("*.info.json"):
        with info_file.open("r") as f:
            info = TaskInfo(**json.load(f))
            if info.status == Status.RUNNING.value and is_pid_running(info.pid):
                cmd_names.append(info.cmd_name)
    return cmd_names

def stop(cmd_name: Optional[str]):
    if cmd_name is None:
        cmd_names: list[str] = get_running_tasks()
        if not cmd_names:
            print("没有正在运行的任务可供停止")
            return
        if len(cmd_names) > 1:
            print("请选择要停止的任务:")
            for i, name in enumerate(cmd_names, 1):
                print(f"{i}. {name}")
            choice = input("输入任务编号: ")
            try:
                index = int(choice) - 1
                cmd_name = cmd_names[index]
            except (ValueError, IndexError):
                print("无效选择，操作取消")
                return
        else:
            cmd_name = cmd_names[0]

    info_file = get_info_path(cmd_name)
    if not info_file.exists():
        print(f"任务 [{cmd_name}] 不存在")
        return

    with info_file.open("r") as f:
        info = TaskInfo(**json.load(f))
    if info.status != Status.RUNNING.value or not is_pid_running(info.pid):
        print(f"任务 [{cmd_name}] 未在运行中")
        return
    os.killpg(os.getpgid(info.pid), signal.SIGTERM)
    info.status = Status.STOPPED.value
    info.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    info.duration = (datetime.strptime(info.end_time, "%Y-%m-%d %H:%M:%S.%f") - datetime.strptime(info.start_time, "%Y-%m-%d %H:%M:%S.%f")).total_seconds()
    with info_file.open("w") as f:
        json.dump(asdict(info), f, indent=4)
    print(f"任务 [{cmd_name}] 已停止")

def watch(cmd_name: Optional[str], num_lines: int):
    if cmd_name is None:
        running_tasks = get_running_tasks()
        if len(running_tasks) == 1:
            cmd_name = running_tasks[0]
            print(f"检测到唯一运行任务 [{cmd_name}]，直接进入日志查看模式")
        else:
            all_tasks = [f.stem for f in LOG_DIR.glob("*.log")]
            if not all_tasks:
                print("当前没有任何任务")
                return
            print("当前没有正在运行的任务。可用任务列表:")
            for i, task in enumerate(all_tasks, start=1):
                print(f"{i}. {task}")
            try:
                choice = int(input("请选择任务编号以查看日志: "))
                if 1 <= choice <= len(all_tasks):
                    cmd_name = all_tasks[choice - 1]
                else:
                    print("无效的选择")
                    return
            except ValueError:
                print("无效输入")
                return

    log_file = LOG_DIR / f"{cmd_name}.log"
    tail_log(log_file, num_lines)

def get_stopped_tasks() -> list[str]:
    cmd_names = []
    for info_file in LOG_DIR.glob("*.info.json"):
        with info_file.open("r") as f:
            info = TaskInfo(**json.load(f))
            if info.status in {Status.STOPPED.value, Status.DONE.value}:
                cmd_names.append(info.cmd_name)
            if not is_pid_running(info.pid):
                cmd_names.append(info.cmd_name)
    return cmd_names

def clear():
    confirm = input(f"确定要清空日志目录 [{LOG_DIR}] 吗？此操作不可撤销！(y/N): ")
    if confirm.lower() == 'y':
        tasks = get_stopped_tasks()
        for task in tasks:
            log_file = get_log_path(task)
            info_file = get_info_path(task)
            log_file.unlink(missing_ok=True)
            info_file.unlink(missing_ok=True)
        print("日志目录已清空")
    else:
        print("操作已取消")

def list_():
    all_tasks = []
    for info_file in LOG_DIR.glob("*.info.json"):
        with info_file.open("r") as f:
            info = TaskInfo(**json.load(f))
            all_tasks.append(info)

    if not all_tasks:
        print("当前没有任何任务")
        return

    print(f"{'任务名称':<20} {'状态':<10} {'PID':<10} {'开始时间':<20} {'结束时间':<20} {'持续时间(秒)':<15}")
    print("-" * 95)
    for info in all_tasks:
        end_time = info.end_time if info.end_time else "-"
        duration = f"{info.duration:.2f}" if info.duration else "-"
        print(f"{info.cmd_name:<20} {info.status:<10} {info.pid:<10} {info.start_time:<20} {end_time:<20} {duration:<15}")

def info(cmd_name: str):
    info_file = get_info_path(cmd_name)
    if not info_file.exists():
        print(f"任务 [{cmd_name}] 不存在")
        return

    with info_file.open("r") as f:
        info = TaskInfo(**json.load(f))

    print(f"任务名称: {info.cmd_name}")
    print(f"命令: {info.cmd}")
    print(f"状态: {info.status}")
    print(f"PID: {info.pid}")
    print(f"开始时间: {info.start_time}")
    print(f"结束时间: {info.end_time if info.end_time else '-'}")
    print(f"持续时间(秒): {info.duration if info.duration else '-'}")
    print(f"退出代码: {info.exit_code if info.exit_code is not None else '-'}")

def callback(cmd_name: str, exit_code: int):
    info_file = get_info_path(cmd_name)
    if not info_file.exists():
        print(f"任务 [{cmd_name}] 的信息文件不存在，无法执行回调")
        return

    with info_file.open("r") as f:
        info = TaskInfo(**json.load(f))

    info.exit_code = exit_code
    info.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    info.duration = (datetime.strptime(info.end_time, "%Y-%m-%d %H:%M:%S.%f") - datetime.strptime(info.start_time, "%Y-%m-%d %H:%M:%S.%f")).total_seconds()
    info.status = Status.DONE.value
    print(f"任务 [{cmd_name}] 已完成，退出代码: {exit_code}")

    with info_file.open("w") as f:
        json.dump(asdict(info), f, indent=4)

def rename(old_name: str, new_name: str):
    old_log = get_log_path(old_name)
    old_info = get_info_path(old_name)
    new_log = get_log_path(new_name)
    new_info = get_info_path(new_name)

    if not old_info.exists():
        print(f"任务 [{old_name}] 不存在，无法重命名")
        return
    if new_info.exists():
        print(f"任务 [{new_name}] 已存在，无法重命名为已存在的任务名")
        return

    old_log.rename(new_log)
    old_info.rename(new_info)

    with new_info.open("r") as f:
        info = TaskInfo(**json.load(f))
    info.cmd_name = new_name
    with new_info.open("w") as f:
        json.dump(asdict(info), f, indent=4)

    print(f"任务 [{old_name}] 已重命名为 [{new_name}]")


def main():
    parser = argparse.ArgumentParser(description="任务后台管理工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="启动任务")
    run_parser.add_argument("-w", "--watch", action="store_true", help="实时查看日志")
    run_parser.add_argument("cmd_string", help="要执行的命令")
    run_parser.add_argument("cmd_name", nargs="?", help="任务名称（可选）")

    stop_parser = subparsers.add_parser("stop", help="停止任务")
    stop_parser.add_argument("cmd_name", nargs="?", help="任务名称（可选）")

    watch_parser = subparsers.add_parser("watch", help="查看任务日志")
    watch_parser.add_argument("-n", "--num-lines", type=int, default=10, help="初始展示的日志行数")
    watch_parser.add_argument("cmd_name", nargs="?", help="任务名称（可选）")

    subparsers.add_parser("clear", help="清空日志目录")

    subparsers.add_parser("list", help="列出所有任务")

    info_parser = subparsers.add_parser("info", help="查看任务详细信息")
    info_parser.add_argument("cmd_name", help="任务名称（可选）")

    rename_parser = subparsers.add_parser("rename", help="重命名任务")
    rename_parser.add_argument("old_name", help="旧任务名称")
    rename_parser.add_argument("new_name", help="新任务名称")

    callback_parser = subparsers.add_parser("callback", help="任务完成回调")
    callback_parser.add_argument("cmd_name")
    callback_parser.add_argument("exit_code", type=int)

    args = parser.parse_args()

    LOG_DIR.mkdir(parents=False, exist_ok=True)

    if args.command == "run":
        run(args.cmd_string, args.cmd_name, args.watch)
    elif args.command == "stop":
        stop(args.cmd_name)
    elif args.command == "watch":
        watch(args.cmd_name, args.num_lines)
    elif args.command == "clear":
        clear()
    elif args.command == "list":
        list_()
    elif args.command == "info":
        info(args.cmd_name)
    elif args.command == "callback":
        callback(args.cmd_name, args.exit_code)
    elif args.command == "rename":
        rename(args.old_name, args.new_name)


if __name__ == "__main__":
    main()