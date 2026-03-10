"""
诊断脚本 — 独立运行，逐项检测扫描/USN监控的各个环节
用法：以管理员权限运行
  C:/Users/mmm/.conda/envs/file-manager/python.exe tools/diagnose.py
"""
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import sqlite3
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path

# ─── 常量 ────────────────────────────────────────────────────────────────────
FSCTL_QUERY_USN_JOURNAL  = 0x000900F4
FSCTL_READ_USN_JOURNAL   = 0x000900BB
ERROR_HANDLE_EOF         = 38
ERROR_ACCESS_DENIED      = 5
ERROR_INVALID_FUNCTION   = 1
GENERIC_READ             = 0x80000000
GENERIC_WRITE            = 0x40000000
FILE_SHARE_READ          = 0x00000001
FILE_SHARE_WRITE         = 0x00000002
FILE_SHARE_DELETE        = 0x00000004
OPEN_EXISTING            = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

PROJ_ROOT = Path(__file__).resolve().parent.parent
DB_PATH   = PROJ_ROOT / "data" / "file_index.db"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
# 64 位 Windows 必须声明 restype，否则 HANDLE 被截断为 32 位
_kernel32.CreateFileW.restype             = wintypes.HANDLE
_kernel32.DeviceIoControl.restype         = wintypes.BOOL
_kernel32.CloseHandle.restype             = wintypes.BOOL
_INVALID_HANDLE = wintypes.HANDLE(-1).value

class USN_JOURNAL_DATA(ctypes.Structure):
    _fields_ = [
        ("UsnJournalID",    ctypes.c_uint64),
        ("FirstUsn",        ctypes.c_int64),
        ("NextUsn",         ctypes.c_int64),
        ("LowestValidUsn",  ctypes.c_int64),
        ("MaxUsn",          ctypes.c_int64),
        ("MaximumSize",     ctypes.c_uint64),
        ("AllocationDelta", ctypes.c_uint64),
    ]

class READ_USN_JOURNAL_DATA(ctypes.Structure):
    _fields_ = [
        ("StartUsn",          ctypes.c_int64),
        ("ReasonMask",        ctypes.c_uint32),
        ("ReturnOnlyOnClose", ctypes.c_uint32),
        ("Timeout",           ctypes.c_uint64),
        ("BytesToWaitFor",    ctypes.c_uint64),
        ("UsnJournalID",      ctypes.c_uint64),
    ]

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def ok(msg):   print(f"  \033[92m[OK]\033[0m {msg}")
def fail(msg): print(f"  \033[91m[FAIL]\033[0m {msg}")
def info(msg): print(f"  \033[93m[INFO]\033[0m {msg}")
def sep(title): print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ─── 诊断项 ──────────────────────────────────────────────────────────────────

def check_admin():
    sep("1. 管理员权限检测")
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception as e:
        fail(f"IsUserAnAdmin 调用异常: {e}")
        return False
    if is_admin:
        ok("当前进程以管理员权限运行")
    else:
        fail("当前进程 **没有** 管理员权限！MFT 扫描和 USN 监控均不可用")
        info("请右键 start.bat → 以管理员身份运行")
    return is_admin


def check_database():
    sep("2. 数据库状态")
    if not DB_PATH.exists():
        fail(f"数据库文件不存在: {DB_PATH}")
        return
    ok(f"数据库文件: {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.1f} MB)")
    conn = sqlite3.connect(str(DB_PATH))
    try:
        files_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        snap_count  = conn.execute("SELECT COUNT(*) FROM file_snapshots").fetchone()[0]
        logs_count  = conn.execute("SELECT COUNT(*) FROM scan_logs").fetchone()[0]
        ok(f"files 表: {files_count:,} 条")
        ok(f"file_snapshots 表: {snap_count:,} 条")
        ok(f"scan_logs 表: {logs_count:,} 条")

        last_log = conn.execute(
            "SELECT scan_type, status, started_at, finished_at, total_files, added, deleted, modified "
            "FROM scan_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last_log:
            info(f"最近扫描: type={last_log[0]}, status={last_log[1]}, "
                 f"started={last_log[2]}, finished={last_log[3]}")
            info(f"  total={last_log[4]}, added={last_log[5]}, deleted={last_log[6]}, modified={last_log[7]}")
    finally:
        conn.close()


def check_volume_handle(volume="E:"):
    sep(f"3. 卷句柄打开测试 ({volume})")
    vol_path = rf"\\.\{volume}"
    handle = _kernel32.CreateFileW(
        vol_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == _INVALID_HANDLE:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            fail(f"打开卷 {vol_path} 失败 — 需要管理员权限 (错误码 {err})")
        else:
            fail(f"打开卷 {vol_path} 失败，错误码 {err}")
        return None
    ok(f"卷句柄打开成功: handle={handle}")
    return handle


def check_usn_journal(handle, volume="E:"):
    sep(f"4. USN Journal 查询 ({volume})")
    if handle is None:
        fail("跳过 — 卷句柄不可用")
        return None

    journal_data   = USN_JOURNAL_DATA()
    bytes_returned = ctypes.c_uint32(0)
    ok_result = _kernel32.DeviceIoControl(
        handle,
        FSCTL_QUERY_USN_JOURNAL,
        None, 0,
        ctypes.byref(journal_data),
        ctypes.sizeof(journal_data),
        ctypes.byref(bytes_returned),
        None,
    )
    if not ok_result:
        err = ctypes.get_last_error()
        if err == ERROR_INVALID_FUNCTION:
            fail(f"USN Journal 未启用 (错误码 {err})")
        elif err == ERROR_ACCESS_DENIED:
            fail(f"访问被拒绝 (错误码 {err})")
        else:
            fail(f"FSCTL_QUERY_USN_JOURNAL 失败，错误码 {err}")
        return None

    ok(f"JournalID  = {journal_data.UsnJournalID:#018x}")
    ok(f"FirstUsn   = {journal_data.FirstUsn}")
    ok(f"NextUsn    = {journal_data.NextUsn}")
    ok(f"LowestValid= {journal_data.LowestValidUsn}")
    ok(f"MaxUsn     = {journal_data.MaxUsn}")
    ok(f"MaxSize    = {journal_data.MaximumSize / 1024 / 1024:.1f} MB")
    return journal_data


def check_usn_read_buffer(handle, journal_data, volume="E:"):
    sep(f"5. USN 缓冲区读取测试 ({volume})")
    if handle is None or journal_data is None:
        fail("跳过 — 前置条件不满足")
        return

    # 用 c_ubyte 缓冲区（修复后的方式）
    BUF_SIZE = 65536
    buf_ubyte = (ctypes.c_ubyte * BUF_SIZE)()
    bytes_returned = ctypes.c_uint32(0)

    read_data = READ_USN_JOURNAL_DATA()
    read_data.StartUsn          = journal_data.NextUsn  # 从最新位置开始
    read_data.ReasonMask        = 0xFFFFFFFF            # 所有事件
    read_data.ReturnOnlyOnClose = 0                     # 不等待 close
    read_data.Timeout           = 0
    read_data.BytesToWaitFor    = 0
    read_data.UsnJournalID      = journal_data.UsnJournalID

    ok_result = _kernel32.DeviceIoControl(
        handle,
        FSCTL_READ_USN_JOURNAL,
        ctypes.byref(read_data),
        ctypes.sizeof(read_data),
        buf_ubyte,
        BUF_SIZE,
        ctypes.byref(bytes_returned),
        None,
    )

    if not ok_result:
        err = ctypes.get_last_error()
        if err == ERROR_HANDLE_EOF:
            ok("无新 USN 事件（ERROR_HANDLE_EOF）— 正常，Journal 末尾")
            # 测试 bytes() 转换
            info("测试 bytes(c_ubyte_buf[:0]) ...")
            try:
                _ = bytes(buf_ubyte[:0])
                ok("bytes() 转换成功（空缓冲区）")
            except Exception as e:
                fail(f"bytes() 转换失败: {e}")
            return
        fail(f"FSCTL_READ_USN_JOURNAL 失败，错误码 {err}")
        return

    n = bytes_returned.value
    ok(f"读取到 {n} 字节")

    # 关键测试：bytes() 转换
    info(f"测试 bytes(c_ubyte_buf[:{n}]) ...")
    try:
        raw = bytes(buf_ubyte[:n])
        ok(f"bytes() 转换成功！长度={len(raw)}")
        # 显示前 64 字节
        info(f"前 64 字节: {raw[:64].hex()}")
    except Exception as e:
        fail(f"c_ubyte bytes() 转换失败: {type(e).__name__}: {e}")

    # 对照测试：用 c_byte 看是否会失败
    info("对照测试: 用 c_byte 缓冲区 ...")
    buf_byte = (ctypes.c_byte * BUF_SIZE)()

    read_data2 = READ_USN_JOURNAL_DATA()
    read_data2.StartUsn          = journal_data.NextUsn
    read_data2.ReasonMask        = 0xFFFFFFFF
    read_data2.ReturnOnlyOnClose = 0
    read_data2.Timeout           = 0
    read_data2.BytesToWaitFor    = 0
    read_data2.UsnJournalID      = journal_data.UsnJournalID

    ok2 = _kernel32.DeviceIoControl(
        handle,
        FSCTL_READ_USN_JOURNAL,
        ctypes.byref(read_data2),
        ctypes.sizeof(read_data2),
        buf_byte,
        BUF_SIZE,
        ctypes.byref(bytes_returned),
        None,
    )
    if ok2 and bytes_returned.value > 0:
        n2 = bytes_returned.value
        try:
            raw2 = bytes(buf_byte[:n2])
            info(f"c_byte bytes() 也成功了（长度={len(raw2)}）— 当前数据无>127 字节")
        except ValueError as e:
            fail(f"c_byte bytes() 失败（预期）: {e}")
            info("这就是用户看到的错误！c_ubyte 已修复此问题")
    elif not ok2:
        err = ctypes.get_last_error()
        if err == ERROR_HANDLE_EOF:
            info("c_byte 对照: 无新事件（EOF）")
        else:
            info(f"c_byte 对照: 读取失败 错误码 {err}")


def check_usn_realtime(handle, journal_data, volume="E:", test_dir="E:\\"):
    sep(f"6. USN 实时监控端到端测试 ({volume})")
    if handle is None or journal_data is None:
        fail("跳过 — 前置条件不满足")
        return False

    # 记录当前 NextUsn
    start_usn = journal_data.NextUsn
    info(f"当前 NextUsn = {start_usn}")

    # 创建测试文件
    test_file = os.path.join(test_dir, f"__diag_test_{int(time.time())}.tmp")
    info(f"创建测试文件: {test_file}")
    try:
        with open(test_file, "w") as f:
            f.write("diagnostic test file")
    except Exception as e:
        fail(f"创建测试文件失败: {e}")
        return False
    ok("测试文件已创建")

    # 等待文件系统刷新
    time.sleep(1)

    # 读取 USN 事件
    BUF_SIZE = 65536
    buf = (ctypes.c_ubyte * BUF_SIZE)()
    bytes_returned = ctypes.c_uint32(0)

    read_data = READ_USN_JOURNAL_DATA()
    read_data.StartUsn          = start_usn
    read_data.ReasonMask        = 0xFFFFFFFF
    read_data.ReturnOnlyOnClose = 0
    read_data.Timeout           = 0
    read_data.BytesToWaitFor    = 0
    read_data.UsnJournalID      = journal_data.UsnJournalID

    ok_result = _kernel32.DeviceIoControl(
        handle,
        FSCTL_READ_USN_JOURNAL,
        ctypes.byref(read_data),
        ctypes.sizeof(read_data),
        buf,
        BUF_SIZE,
        ctypes.byref(bytes_returned),
        None,
    )

    found_create = False
    if ok_result and bytes_returned.value > 8:
        n = bytes_returned.value
        raw = bytes(buf[:n])
        ok(f"读取到 {n} 字节 USN 数据")

        # 解析事件
        offset = 8  # 跳过 NextUsn（8字节）
        test_filename = os.path.basename(test_file)
        events_found = 0
        while offset + 60 <= n:
            rec_len = int.from_bytes(raw[offset:offset+4], "little")
            if rec_len < 60 or offset + rec_len > n:
                break
            fn_offset = int.from_bytes(raw[offset+58:offset+60], "little")
            fn_length = int.from_bytes(raw[offset+56:offset+58], "little")
            reason    = int.from_bytes(raw[offset+40:offset+44], "little")
            try:
                fn_start = offset + fn_offset
                filename = raw[fn_start:fn_start+fn_length].decode("utf-16-le")
            except Exception:
                filename = "<decode error>"

            events_found += 1
            if test_filename.lower() in filename.lower():
                reason_str = []
                if reason & 0x00000100: reason_str.append("CREATE")
                if reason & 0x00000200: reason_str.append("DELETE")
                if reason & 0x00002000: reason_str.append("RENAME_NEW")
                if reason & 0x80000000: reason_str.append("CLOSE")
                if reason & 0x00000001: reason_str.append("DATA_OVERWRITE")
                if reason & 0x00000002: reason_str.append("DATA_EXTEND")
                ok(f"捕获到测试文件事件: {filename}, reason={' | '.join(reason_str)} (0x{reason:08x})")
                found_create = True

            offset += rec_len

        info(f"共解析 {events_found} 个 USN 事件")
        if not found_create:
            fail(f"未找到测试文件 '{test_filename}' 的事件")
    elif not ok_result:
        err = ctypes.get_last_error()
        if err == ERROR_HANDLE_EOF:
            fail("无新 USN 事件（但我们刚创建了文件！）")
        else:
            fail(f"读取失败，错误码 {err}")
    else:
        fail(f"返回字节数太少: {bytes_returned.value}")

    # 清理测试文件
    try:
        os.remove(test_file)
        info(f"测试文件已删除: {test_file}")
    except Exception:
        info(f"请手动删除: {test_file}")

    return found_create


def check_backend_api():
    sep("7. 后端 API 连通性测试")
    try:
        import urllib.request
        # scan status
        try:
            resp = urllib.request.urlopen("http://127.0.0.1:8000/api/scan/status", timeout=3)
            data = json.loads(resp.read())
            ok(f"GET /api/scan/status → {json.dumps(data, ensure_ascii=False, indent=2)}")
        except Exception as e:
            fail(f"GET /api/scan/status 失败: {e}")
            info("后端服务可能未启动，请先运行 start.bat")
            return

        # monitor status
        try:
            resp = urllib.request.urlopen("http://127.0.0.1:8000/api/scan/monitor/status", timeout=3)
            data = json.loads(resp.read())
            ok(f"GET /api/scan/monitor/status →")
            print(f"         running: {data.get('running')}")
            print(f"         events_processed: {data.get('events_processed')}")
            for vol in data.get("watching_volumes", []):
                print(f"         卷 {vol['volume']}: status={vol['status']}, "
                      f"events={vol['events_processed']}, upserted={vol['upserted']}, "
                      f"deleted={vol['deleted']}, skipped={vol['skipped']}, "
                      f"restarts={vol['restart_count']}")
                if vol.get("last_error"):
                    fail(f"  last_error: {vol['last_error']}")
        except Exception as e:
            fail(f"GET /api/scan/monitor/status 失败: {e}")

        # stats overview
        try:
            resp = urllib.request.urlopen("http://127.0.0.1:8000/api/stats/overview", timeout=3)
            data = json.loads(resp.read())
            ok(f"GET /api/stats/overview → total_files={data.get('total_files')}, "
               f"last_scan={data.get('last_scan')}, db_size_mb={data.get('db_size_mb')}")
        except Exception as e:
            fail(f"GET /api/stats/overview 失败: {e}")

    except ImportError:
        fail("无法 import urllib.request")


def check_mft_scanner():
    sep("8. MFT Scanner 模块检测")
    # 把项目根加入 sys.path
    sys.path.insert(0, str(PROJ_ROOT))
    try:
        from backend.services import mft_scanner
        ok("import mft_scanner 成功")
        is_admin = mft_scanner.is_admin()
        if is_admin:
            ok(f"mft_scanner.is_admin() = True")
        else:
            fail(f"mft_scanner.is_admin() = False — MFT 扫描不可用")
        return is_admin
    except ImportError as e:
        fail(f"import mft_scanner 失败: {e}")
        return False
    except Exception as e:
        fail(f"mft_scanner 检测异常: {e}")
        return False


def check_usn_monitor_code():
    sep("9. USN Monitor 代码检查")
    usn_file = PROJ_ROOT / "backend" / "services" / "usn_monitor.py"
    if not usn_file.exists():
        fail(f"文件不存在: {usn_file}")
        return

    content = usn_file.read_text(encoding="utf-8")

    # 检查 c_byte vs c_ubyte
    if "ctypes.c_byte *" in content and "c_ubyte" not in content.split("ctypes.c_byte *")[0][-100:]:
        # 检查是否还有 c_byte 缓冲区
        import re
        c_byte_bufs = re.findall(r'ctypes\.c_byte\s*\*', content)
        c_ubyte_bufs = re.findall(r'ctypes\.c_ubyte\s*\*', content)
        if c_byte_bufs:
            fail(f"发现 {len(c_byte_bufs)} 处 ctypes.c_byte * 缓冲区（应改为 c_ubyte）")
            for i, m in enumerate(c_byte_bufs):
                # 找到行号
                pos = content.find(m)
                line_no = content[:pos].count('\n') + 1
                info(f"  第 {line_no} 行: {m}")
        if c_ubyte_bufs:
            ok(f"发现 {len(c_ubyte_bufs)} 处 ctypes.c_ubyte * 缓冲区（正确）")
    else:
        import re
        c_ubyte_bufs = re.findall(r'ctypes\.c_ubyte\s*\*', content)
        c_byte_bufs = re.findall(r'ctypes\.c_byte\s*\*', content)
        if c_ubyte_bufs and not c_byte_bufs:
            ok(f"缓冲区全部使用 c_ubyte（{len(c_ubyte_bufs)} 处）— 正确")
        elif c_byte_bufs:
            fail(f"仍有 c_byte 缓冲区: {len(c_byte_bufs)} 处")
        else:
            info("未找到任何缓冲区定义")

    # 检查 _POLL_INTERVAL
    import re
    m = re.search(r'_POLL_INTERVAL\s*=\s*([\d.]+)', content)
    if m:
        info(f"_POLL_INTERVAL = {m.group(1)} 秒")

    # 检查 _MAX_RESTARTS
    m = re.search(r'_MAX_RESTARTS\s*=\s*(\d+)', content)
    if m:
        info(f"_MAX_RESTARTS = {m.group(1)}")


def check_db_after_file_add(test_dir="E:\\"):
    """在后端服务运行的情况下，添加文件后检查 DB 是否更新"""
    sep("10. 端到端测试：添加文件 → DB 更新")

    if not DB_PATH.exists():
        fail("数据库不存在")
        return

    test_file = os.path.join(test_dir, f"__e2e_test_{int(time.time())}.txt")

    # 记录当前 files 数量
    conn = sqlite3.connect(str(DB_PATH))
    count_before = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn.close()
    info(f"添加前 files 表: {count_before:,} 条")

    # 创建文件
    info(f"创建测试文件: {test_file}")
    try:
        with open(test_file, "w") as f:
            f.write("e2e test " + datetime.now().isoformat())
    except Exception as e:
        fail(f"创建文件失败: {e}")
        return

    # 等待 USN 监控处理（轮询间隔 2 秒 + 处理时间）
    info("等待 6 秒让 USN 监控处理事件...")
    time.sleep(6)

    # 检查 DB
    conn = sqlite3.connect(str(DB_PATH))
    count_after = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    # 精确查找测试文件
    row = conn.execute(
        "SELECT id, file_name, file_path FROM files WHERE file_path = ?",
        (test_file,)
    ).fetchone()
    conn.close()

    info(f"添加后 files 表: {count_after:,} 条 (差值: {count_after - count_before})")

    if row:
        ok(f"测试文件已写入 DB: id={row[0]}, name={row[1]}")
    else:
        fail(f"测试文件 **未写入** DB！USN 监控可能未工作")
        # 检查 API
        try:
            import urllib.request
            resp = urllib.request.urlopen("http://127.0.0.1:8000/api/scan/monitor/status", timeout=3)
            data = json.loads(resp.read())
            info(f"当前 USN 监控状态: running={data.get('running')}")
            for vol in data.get("watching_volumes", []):
                info(f"  卷 {vol['volume']}: status={vol['status']}, "
                     f"last_error={vol.get('last_error', '')}")
        except Exception:
            info("无法连接后端 API")

    # 清理
    try:
        os.remove(test_file)
        info(f"测试文件已删除")
        # 等待删除事件
        time.sleep(3)
        conn = sqlite3.connect(str(DB_PATH))
        row2 = conn.execute(
            "SELECT id FROM files WHERE file_path = ?",
            (test_file,)
        ).fetchone()
        conn.close()
        if row2:
            info("删除事件尚未被 USN 监控处理（可能需要更长时间）")
        else:
            ok("删除事件也被 USN 监控正确处理了")
    except Exception:
        info(f"请手动删除: {test_file}")


# ─── 主函数 ───────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  文件管理系统诊断工具")
    print(f"  时间: {datetime.now().isoformat()}")
    print(f"  项目: {PROJ_ROOT}")
    print(f"  Python: {sys.executable}")
    print("=" * 60)

    # 1. 管理员权限
    is_admin = check_admin()

    # 2. 数据库
    check_database()

    # 3-6. 卷/USN 测试（需要管理员权限）
    handle = check_volume_handle("E:")
    journal_data = check_usn_journal(handle, "E:")
    check_usn_read_buffer(handle, journal_data, "E:")
    usn_works = check_usn_realtime(handle, journal_data, "E:", "E:\\")

    if handle and handle != _INVALID_HANDLE:
        _kernel32.CloseHandle(handle)

    # 7. 后端 API
    check_backend_api()

    # 8. MFT Scanner
    check_mft_scanner()

    # 9. 代码检查
    check_usn_monitor_code()

    # 10. 端到端测试（只在后端运行时执行）
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8000/api/scan/status", timeout=2)
        check_db_after_file_add("E:\\")
    except Exception:
        info("\n跳过端到端测试 — 后端服务未运行")

    # 总结
    sep("诊断总结")
    if not is_admin:
        fail("根本原因可能是：未以管理员权限运行")
        info("解决方案：右键 start.bat → 以管理员身份运行")
    if not usn_works:
        fail("USN Journal 读取未能捕获到文件变更事件")
    print()


if __name__ == "__main__":
    main()
